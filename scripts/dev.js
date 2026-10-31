#!/usr/bin/env node
// One-command dev launcher: starts the FastAPI backend and the Next.js frontend
// together so the site runs on live data from the API.
//
//   npm run dev        # from the repo root
//
// No external dependencies. Ctrl+C stops both processes.
//
// The API port defaults to 8000 and can be overridden with KETSA_API_PORT; the
// frontend port defaults to 3000 via KETSA_WEB_PORT. Both are needed when
// something else already holds the defaults. `--api-port N` / `--web-port N`
// override the env vars; use `npm run dev:alt-ports` when another project owns
// 3000/8000 on this machine.
//
// The port chosen here is what gets handed to Next (both the server-side fetches
// and the public WebSocket origin), so the launcher and the frontend can never
// disagree about where the API lives. Next.js does not override env vars that
// are already set, so these win over frontend/.env.local.
//
// The same reasoning pins the *backend's* view of the two URLs the Auth0 social
// login derives from: KETSA_PUBLIC_BASE_URL (where Auth0 redirects the browser
// back to — it must be browser-reachable) and KETSA_FRONTEND_URL (where the
// single-use ticket is then handed off). If those drift from the ports actually
// in use, social login fails on the last hop with a 404 instead of at startup.
// Real env vars win over backend/.env, so the launcher is authoritative here.

const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');

const root = path.resolve(__dirname, '..');
const backendDir = path.join(root, 'backend');
const frontendDir = path.join(root, 'frontend');

// `--api-port N` / `--web-port N` win over the env vars so a package.json
// script can pin non-default ports without a cross-platform env shim
// (Windows `set` vs POSIX `VAR=...`, i.e. without adding cross-env).
function cliPort(flag) {
  const i = process.argv.indexOf(`--${flag}`);
  if (i === -1 || !process.argv[i + 1]) return undefined;
  const value = Number(process.argv[i + 1]);
  return Number.isInteger(value) && value > 0 && value < 65536 ? value : undefined;
}

// Explicit choices (CLI flag or env var) are honoured as-is. Only the defaults
// fall forward, so `npm run dev` still works on a machine where another project
// already owns 3000/8000 — previously Next failed with EADDRINUSE, the
// launcher tore the API back down, and the site (and its markets) never came up.
const explicitApiPort =
  cliPort('api-port') ?? (process.env.KETSA_API_PORT ? Number(process.env.KETSA_API_PORT) : undefined);
const explicitWebPort =
  cliPort('web-port') ?? (process.env.KETSA_WEB_PORT ? Number(process.env.KETSA_WEB_PORT) : undefined);
let apiPort = explicitApiPort ?? 8000;
let webPort = explicitWebPort ?? 3000;
let apiUrl = `http://127.0.0.1:${apiPort}`;
let webUrl = `http://localhost:${webPort}`;

/** True when nothing is listening on `port` (binds then immediately releases). */
function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once('error', () => resolve(false));
    server.listen({ port, exclusive: true }, () => {
      server.close(() => resolve(true));
    });
  });
}

/** First free port at or after `preferred`; explicit ports are never moved. */
async function freePort(preferred, explicit) {
  if (explicit) return preferred;
  for (let port = preferred; port < preferred + 50 && port < 65536; port += 1) {
    if (await isPortFree(port)) return port;
  }
  throw new Error(`no free port found in ${preferred}-${preferred + 49}`);
}

const CYAN = '\u001b[36m';
const MAGENTA = '\u001b[35m';
const RESET = '\u001b[0m';

function pickPython() {
  const candidates = [
    path.join(backendDir, '.venv', 'Scripts', 'python.exe'),
    path.join(backendDir, 'venv', 'Scripts', 'python.exe'),
    'python',
    'python3',
  ];
  for (const candidate of candidates) {
    if (candidate.includes(path.sep) && !fs.existsSync(candidate)) continue;
    return candidate;
  }
  return 'python';
}

function pickWeb() {
  // Modern Node (>= 20.12 / 22 / 24) refuses to spawn the `npm.cmd` shim on
  // Windows without a shell (it throws EINVAL), so the reliable path is to run
  // Next's own entry point with this same Node binary.
  const nextBin = path.join(frontendDir, 'node_modules', 'next', 'dist', 'bin', 'next');
  if (fs.existsSync(nextBin)) {
    return {
      command: process.execPath,
      // -p is explicit: left to itself Next would silently fall forward to the
      // next free port, and nothing downstream would know which one it picked.
      args: [nextBin, 'dev', '-p', String(webPort)],
      shell: false,
    };
  }
  // Fallback when dependencies are not installed yet: go through npm, which
  // needs a shell for the same .cmd reason.
  return {
    command: process.platform === 'win32' ? 'npm.cmd' : 'npm',
    args: ['run', 'dev', '--', '-p', String(webPort)],
    shell: true,
  };
}

const webCmd = pickWeb();

const api = spawn(
  pickPython(),
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(apiPort), '--reload'],
  {
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    // Pin the two URLs the Auth0 social flow derives from, so the redirect
    // target can never point at a port this launcher is not serving.
    env: {
      ...process.env,
      KETSA_PUBLIC_BASE_URL: apiUrl,
      KETSA_FRONTEND_URL: webUrl,
    },
  },
);

const web = spawn(
  webCmd.command,
  webCmd.args,
  {
    cwd: frontendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: webCmd.shell,
    // Pin the frontend to the API this launcher just started.
    env: {
      ...process.env,
      KETSA_BACKEND_URL: apiUrl,
      NEXT_PUBLIC_KETSA_BACKEND_URL: apiUrl,
    },
  },
);

function pump(child, name, color) {
  const handler = (buf) => {
    String(buf)
      .split(/\r?\n/)
      .filter(Boolean)
      .forEach((line) => process.stdout.write(`${color}[${name}]${RESET} ${line}\n`));
  };
  child.stdout.on('data', handler);
  child.stderr.on('data', handler);
}

function stop(signal) {
  try {
    api.kill(signal);
  } catch {
    /* ignore */
  }
  try {
    web.kill(signal);
  } catch {
    /* ignore */
  }
}

let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  stop('SIGTERM');
  setTimeout(() => process.exit(code), 400);
}

api.on('exit', (code) => {
  process.stdout.write(`${CYAN}[api]${RESET} backend exited (${code})\n`);
  shutdown(code || 0);
});
web.on('exit', (code) => {
  process.stdout.write(`${MAGENTA}[web]${RESET} frontend exited (${code})\n`);
  shutdown(code || 0);
});

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

pump(api, 'api', CYAN);
pump(web, 'web', MAGENTA);

process.stdout.write(`${CYAN}[api]${RESET} starting FastAPI backend (${apiUrl})...\n`);
process.stdout.write(`${MAGENTA}[web]${RESET} starting Next.js frontend (${webUrl})...\n`);
if (apiPort !== 8000 || webPort !== 3000) {
  process.stdout.write(
    `${CYAN}[api]${RESET} non-default ports — Auth0's Allowed Callback URL must be exactly:\n`,
  );
  process.stdout.write(`${CYAN}[api]${RESET}   ${apiUrl}/api/auth/social/callback\n`);
}