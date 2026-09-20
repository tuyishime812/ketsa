#!/usr/bin/env node
// One-command dev launcher: starts the FastAPI backend and the Next.js frontend
// together so the site runs on live data from the API.
//
//   npm run dev        # from the repo root
//
// No external dependencies. Ctrl+C stops both processes.
//
// The API port defaults to 8000 and can be overridden with KETSA_API_PORT. The
// port chosen here is what gets handed to Next (both the server-side fetches and
// the public WebSocket origin), so the launcher and the frontend can never
// disagree about where the API lives. Next.js does not override env vars that
// are already set, so these win over frontend/.env.local.

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const backendDir = path.join(root, 'backend');
const frontendDir = path.join(root, 'frontend');

const apiPort = Number(process.env.KETSA_API_PORT || 8000);
const apiUrl = `http://127.0.0.1:${apiPort}`;

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
    return { command: process.execPath, args: [nextBin, 'dev'], shell: false };
  }
  // Fallback when dependencies are not installed yet: go through npm, which
  // needs a shell for the same .cmd reason.
  return {
    command: process.platform === 'win32' ? 'npm.cmd' : 'npm',
    args: ['run', 'dev'],
    shell: true,
  };
}

const webCmd = pickWeb();

const api = spawn(
  pickPython(),
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(apiPort), '--reload'],
  { cwd: backendDir, stdio: ['ignore', 'pipe', 'pipe'] },
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
process.stdout.write(`${MAGENTA}[web]${RESET} starting Next.js frontend (http://localhost:3000)...\n`);