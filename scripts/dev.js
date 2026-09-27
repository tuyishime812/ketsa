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
// something else already holds the defaults.
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
const path = require('path');

const root = path.resolve(__dirname, '..');
const backendDir = path.join(root, 'backend');
const frontendDir = path.join(root, 'frontend');

const apiPort = Number(process.env.KETSA_API_PORT || 8000);
const apiUrl = `http://127.0.0.1:${apiPort}`;
const webPort = Number(process.env.KETSA_WEB_PORT || 3000);
const webUrl = `http://localhost:${webPort}`;

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