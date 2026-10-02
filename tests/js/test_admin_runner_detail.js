/* Owner runner drill-down: secrets/source are only returned after the explicit
 * reveal button, links are clickable, and closing the modal clears revealed text. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(root, 'templates/admin_panel.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'static/admin_runner.js'), 'utf8');
const dom = new JSDOM(`<!doctype html><body>${html}</body>`, {
  url: 'https://site.example/', runScripts: 'outside-only', pretendToBeVisual: true,
});
const w = dom.window, d = w.document;
const calls = [], toasts = [], copied = [];
const detail = {
  runner: { id: 7, label: 'Build runner', url: 'https://runner.example',
    health_url: 'https://runner.example/health', online: true, enabled: true,
    checked_at: 'today', reason: 'Runner answered /health.', jobs: 1, capacity: 8,
    mem_mb: 44, safe_mb: 512, free_mb: 468, assigned_jobs: 1 },
  jobs: [{ id: 91, runner_job_id: 'live-91', name: 'saved bot', owner: 'alice',
    language: 'python', status: 'running', desired_state: 'running', uptime_s: 90,
    restarts: 2, mem_mb: 42, peak_mem_mb: 83, last_exit_reason: 'crash',
    last_exit_code: 1, web_url: 'https://runner.example/live/saved-bot/',
    telegram_bot_url: 'https://t.me/saved_bot', recent_actions: [] }],
  history: [], setup: { note: 'Host restart is not configured; health/recovery only.' },
};
w.api = async (url, method, body, auth) => {
  calls.push({ url, method, body, auth });
  if (url === '/admin/runners/7') return detail;
  if (url.startsWith('/admin/runners/by-url?url=')) return {
    ...detail, runner: { ...detail.runner, id: null, label: 'Configured runner', url: 'https://configured.example' },
  };
  if (url === '/admin/runners/7/secret') return {
    url: 'https://runner.example', secret: 'runner-explicit-secret',
    health_url: 'https://runner.example/health',
  };
  if (url === '/admin/jobs/91/settings') return {
    job: { id: 91, name: 'saved bot', language: 'python', code: "print('private-source')",
      desired_state: 'running', repo_url: '', created_at: 'today' },
    env: { BOT_TOKEN: '123456:AA-explicit-job-token', ADMIN_ID: '12' }, env_readable: true,
  };
  if (url.endsWith('/wake')) return { ok: true, message: 'Runner answered.' };
  return { ok: true, message: 'Action accepted.' };
};
w.toast = (...args) => toasts.push(args);
w._admFriendlyErr = (_e, fallback) => fallback;
w.openModal = id => { d.getElementById(id).classList.remove('hidden'); d.getElementById(id).classList.add('open'); };
w.closeModal = modal => { modal.classList.remove('open'); };
w.openAdminJob = () => {};
w.loadAdminPanel = async () => {};
w.confirm = () => true;
Object.defineProperty(w.navigator, 'clipboard', { configurable: true, value: {
  writeText: async value => { copied.push(value); },
} });
w.eval(js);

(async () => {
  await w.openAdminRunner(7);
  const body = d.getElementById('admRunnerBody');
  const firstRender = body.textContent;
  if (!/Build runner/.test(d.getElementById('admRunnerTitle').textContent)) throw Error('runner title missing');
  if (!/saved bot/.test(firstRender) || !/Restart\s*\/\s*recover this bot/.test(firstRender)) throw Error('assigned job/actions missing');
  if (!body.querySelector('a[href="https://runner.example/health"]')) throw Error('health URL is not clickable');
  if (!body.querySelector('a[href="https://runner.example/live/saved-bot/"]')) throw Error('job URL is not clickable');
  if (/runner-explicit-secret|private-source|explicit-job-token/.test(firstRender)) throw Error('sensitive values appeared before reveal');

  const jobReveal = [...body.querySelectorAll('button')].find(b => /Show & copy code/.test(b.textContent));
  if (!jobReveal) throw Error('job reveal button missing');
  jobReveal.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  const jobField = body.querySelector('.adm-runner-job-settings');
  if (!jobField || jobField.hidden || !/private-source/.test(jobField.value) || !/explicit-job-token/.test(jobField.value)) {
    throw Error('job source/secrets were not explicitly revealed');
  }
  if (!copied.some(value => /private-source/.test(value))) throw Error('revealed settings were not copied');

  const runnerReveal = [...body.querySelectorAll('button')].find(b => /Show & copy saved runner settings/.test(b.textContent));
  if (!runnerReveal) throw Error('runner reveal button missing');
  runnerReveal.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  const runnerField = d.getElementById('admRunnerSecretSettings');
  if (!runnerField || runnerField.hidden || !/runner-explicit-secret/.test(runnerField.value)) throw Error('runner secret not explicitly revealed');

  await w.openAdminRunner('https://configured.example');
  if (!calls.some(call => call.url === '/admin/runners/by-url?url=https%3A%2F%2Fconfigured.example')) {
    throw Error('environment runner details did not use the allowlisted URL endpoint');
  }
  if (!/Configured runner/.test(d.getElementById('admRunnerTitle').textContent)) throw Error('environment runner title missing');

  w.closeModal(d.getElementById('admRunnerModal'));
  await new Promise(resolve => setTimeout(resolve, 0));
  if (!jobField.hidden || jobField.value || !runnerField.hidden || runnerField.value) throw Error('revealed values were not cleared after closing');
  if (!calls.every(call => call.auth === true)) throw Error('admin API calls were not authenticated');
  console.log('admin runner detail, explicit reveal/copy and close-clearing checks passed');
  dom.window.close();
})().catch(error => { console.error(error); process.exitCode = 1; dom.window.close(); });
