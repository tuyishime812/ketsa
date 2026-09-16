#!/usr/bin/env node
// One-command dev launcher: starts the FastAPI backend (port 8000) and the
// Next.js frontend (port 3000) together so the site runs on live demo data.
//
//   npm run dev        # from the repo root
//
// No external dependencies. Ctrl+C stops both processes.

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const backendDir = path.join(root, 'backend');
const frontendDir = path.join(root, 'frontend');

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

const api = spawn(
  pickPython(),
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload'],
  { cwd: backendDir, stdio: ['ignore', 'pipe', 'pipe'] },
);

const web = spawn(
  process.platform === 'win32' ? 'npm.cmd' : 'npm',
  ['run', 'dev'],
  { cwd: frontendDir, stdio: ['ignore', 'pipe', 'pipe'] },
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

process.stdout.write(`${CYAN}[api]${RESET} starting FastAPI backend (http://127.0.0.1:8000)...\n`);
process.stdout.write(`${MAGENTA}[web]${RESET} starting Next.js frontend (http://localhost:3000)...\n`);