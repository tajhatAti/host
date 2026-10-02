/* Small owner-only runner drill-down. Rendering stays separate from pro.js's
 * general admin/dashboard code; all user/database strings use textContent. */
(function (w, d) {
  'use strict';

  function node(tag, text, cls) {
    const el = d.createElement(tag);
    if (text !== undefined && text !== null) el.textContent = String(text);
    if (cls) el.className = cls;
    return el;
  }

  function safeLink(url, label) {
    if (!url) return null;
    try {
      const parsed = new URL(String(url), w.location.href);
      if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
      const a = node('a', label || parsed.href, 'adm-link');
      a.href = parsed.href;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      return a;
    } catch (_) { return null; }
  }

  function button(text, handler, cls) {
    const b = node('button', text, cls || 'btn-ghost sm');
    b.type = 'button';
    b.addEventListener('click', handler);
    return b;
  }

  function runnerApiPath(id, action) {
    const value = String(id == null ? '' : id);
    if (/^\d+$/.test(value)) return `/admin/runners/${encodeURIComponent(value)}${action ? `/${action}` : ''}`;
    return `/admin/runners/by-url${action ? `/${action}` : ''}?url=${encodeURIComponent(value)}`;
  }

  function section(title, hint) {
    const head = node('div', undefined, 'adm-panel-head adm-runner-detail-section-head');
    head.appendChild(node('h3', title));
    if (hint) head.appendChild(node('span', hint, 'adm-hint'));
    return head;
  }

  function exitReason(job) {
    if (job.last_exit_text) return job.last_exit_text;
    const words = {
      oom: 'Stopped after using more memory than its limit.',
      crash: 'Crashed; read the recent job log for the exact error.',
      crash_loop: 'Stopped after repeated crashes to protect this runner.',
      manual: 'Stopped by request.',
      limit: 'Stopped to protect the runner because host memory crossed its safe limit.',
      isolation: 'Stopped by the per-job isolation guard; sibling bots were left running.',
      exit: 'Finished normally.',
      'workspace missing': 'Runner could not find this app’s saved workspace after recovery.'
    };
    return words[job.last_exit_reason] || (job.last_exit_reason ? `Last exit: ${job.last_exit_reason}` : '');
  }

  function _clearSecret() {
    const boxes = d.querySelectorAll('#admRunnerModal .adm-runner-secret-settings, #admRunnerModal .adm-runner-job-settings, #admJobModal .adm-admin-job-settings');
    boxes.forEach(box => { box.value = ''; box.hidden = true; });
  }

  let _observedModal = null;
  function observeModalClose(modal) {
    if (!modal || modal === _observedModal) return;
    _observedModal = modal;
    if (w.MutationObserver) {
      const observer = new w.MutationObserver(() => {
        if (!modal.classList.contains('open')) _clearSecret();
      });
      observer.observe(modal, { attributes: true, attributeFilter: ['class'] });
    }
  }

  function copyText(text, fallback) {
    if (w.navigator.clipboard && w.navigator.clipboard.writeText) {
      return w.navigator.clipboard.writeText(text).then(() => true).catch(() => copyFallback(fallback));
    }
    return Promise.resolve(copyFallback(fallback));
  }

  function copyFallback(textarea) {
    if (!textarea) return false;
    textarea.hidden = false;
    textarea.focus();
    textarea.select();
    try { return !!d.execCommand('copy'); } catch (_) { return false; }
  }

  async function revealRunnerSettings(id, buttonEl) {
    const field = d.getElementById('admRunnerSecretSettings');
    if (!field) return;
    try {
      buttonEl.disabled = true;
      buttonEl.textContent = 'Reading saved settings…';
      const data = await w.api(runnerApiPath(id, 'secret'), 'GET', null, true);
      if (!field.closest('.ah-modal')?.classList.contains('open')) return;
      const settings = [
        `RUNNER_URL=${data.url || ''}`,
        `RUNNER_SERVICE_SECRET=${data.secret || ''}`,
        `Health=${data.health_url || ''}`
      ].join('\n');
      field.value = settings;
      field.hidden = false;
      const copied = await copyText(settings, field);
      if (typeof w.toast === 'function') {
        w.toast(copied ? 'Saved runner settings copied. Keep the secret private.' : 'Settings shown below — select and copy them.', copied ? 'success' : 'info');
      }
    } catch (e) {
      if (typeof w.toast === 'function') w.toast((w._admFriendlyErr && w._admFriendlyErr(e, 'Could not read runner settings')) || e.message, 'error');
    } finally {
      buttonEl.disabled = false;
      buttonEl.textContent = 'Show & copy saved runner settings';
    }
  }

  async function revealJobSettings(jobId, field, buttonEl) {
    if (!field || !buttonEl) return;
    observeModalClose(field.closest('.ah-modal'));
    try {
      buttonEl.disabled = true;
      buttonEl.textContent = 'Reading saved source/settings…';
      const data = await w.api(`/admin/jobs/${encodeURIComponent(jobId)}/settings`, 'GET', null, true);
      if (!field.closest('.ah-modal')?.classList.contains('open')) return;
      const job = data.job || {};
      const env = data.env || {};
      const lines = [
        `# Saved app settings`,
        `name=${job.name || ''}`,
        `job_id=${job.id || jobId}`,
        `language=${job.language || ''}`,
        `desired_state=${job.desired_state || ''}`,
        `created_at=${job.created_at || ''}`,
        `updated_at=${job.updated_at || ''}`,
        `repository=${job.repo_url || ''}`,
        `repository_entry=${job.repo_entry || ''}`,
        `repository_commit=${job.repo_commit || ''}`,
        `auto_deploy=${job.auto_deploy == null ? '' : job.auto_deploy}`,
        '',
        '# Saved environment variables (values shown only after this explicit reveal)'
      ];
      Object.keys(env).sort().forEach(key => lines.push(`${key}=${env[key] == null ? '' : env[key]}`));
      if (!data.env_readable) lines.push('# The saved environment could not be read or restored from this runner.');
      lines.push('', '# Saved source code', job.code || '# No source code is saved in this job row.');
      const settings = lines.join('\n');
      field.value = settings;
      field.hidden = false;
      const copied = await copyText(settings, field);
      if (typeof w.toast === 'function') {
        w.toast(copied ? 'Saved source, settings and environment copied.' : 'Saved source/settings shown below — select and copy them.', copied ? 'success' : 'info');
      }
    } catch (e) {
      if (typeof w.toast === 'function') w.toast((w._admFriendlyErr && w._admFriendlyErr(e, 'Could not read saved app settings')) || e.message, 'error');
    } finally {
      buttonEl.disabled = false;
      buttonEl.textContent = 'Show & copy code, settings & saved secrets';
    }
  }

  function renderJobCard(job, runner, runnerId) {
    const card = node('article', undefined, 'adm-runner-job');
    const top = node('div', undefined, 'adm-runner-job-head');
    const name = node('div', undefined, 'adm-runner-job-name');
    name.appendChild(node('b', `${job.name || 'Job'}${job.id ? ` · #${job.id}` : ''}`));
    name.appendChild(node('span', `${job.owner || '—'} · ${job.language || '—'}`, 'adm-hint'));
    const st = String(job.status || 'unknown').toLowerCase();
    top.append(name, node('span', st, `adm-pill${st === 'running' ? ' ok' : (['unknown','missing','crashed'].includes(st) ? ' warn' : '')}`));
    card.appendChild(top);

    const facts = node('div', undefined, 'adm-runner-job-facts');
    facts.appendChild(node('span', `Runner job id: ${job.runner_job_id || '—'}`));
    facts.appendChild(node('span', `Desired: ${job.desired_state || '—'}`));
    facts.appendChild(node('span', `Uptime: ${job.uptime_s ? (w._fmtUptime ? w._fmtUptime(job.uptime_s) : `${job.uptime_s}s`) : '—'}`));
    facts.appendChild(node('span', `Restarts: ${job.restarts == null ? '—' : job.restarts}`));
    facts.appendChild(node('span', `Memory: ${job.mem_mb == null ? '—' : `${Math.round(job.mem_mb)}MB now`}`));
    facts.appendChild(node('span', `Peak: ${job.peak_mem_mb == null ? '—' : `${Math.round(job.peak_mem_mb)}MB`}`));
    if (job.last_exit_code != null) facts.appendChild(node('span', `Last exit code: ${job.last_exit_code}`));
    card.appendChild(facts);

    const reason = exitReason(job) || job.status_reason;
    if (reason) card.appendChild(node('p', reason, `adm-runner-job-reason${job.last_exit_reason || st === 'missing' || st === 'unknown' ? ' warn' : ''}`));
    const links = node('div', undefined, 'adm-runner-job-links');
    const web = safeLink(job.web_url, 'Open app URL');
    const bot = safeLink(job.telegram_bot_url, 'Open Telegram bot');
    const repo = safeLink(job.repo_url, 'Source repository');
    if (web) links.appendChild(web);
    if (bot) links.appendChild(bot);
    if (repo) links.appendChild(repo);
    if (job.id && typeof w.openAdminJob === 'function') {
      links.appendChild(button('Full job details', () => {
        const modal = d.getElementById('admRunnerModal');
        if (modal && typeof w.closeModal === 'function') w.closeModal(modal);
        w.openAdminJob(job.id);
      }));
    }
    if (links.childNodes.length) card.appendChild(links);

    const revisions = job.recent_actions || [];
    if (revisions.length) {
      const details = node('details', undefined, 'adm-runner-job-history');
      details.appendChild(node('summary', `${revisions.length} recent saved change(s)`));
      const list = node('ul');
      revisions.forEach(r => list.appendChild(node('li',
        `v${r.version || '—'} · ${r.action || 'change'} · ${r.status || '—'} · ${r.created_at || ''}${r.error ? ` · ${r.error}` : ''}`)));
      details.appendChild(list);
      card.appendChild(details);
    }

    let settingsField = null;
    if (job.id) {
      settingsField = node('textarea', undefined, 'input-text adm-runner-secret-settings adm-runner-job-settings');
      settingsField.id = `admRunnerJobSettings${job.id}`;
      settingsField.readOnly = true; settingsField.rows = 7; settingsField.hidden = true;
      settingsField.setAttribute('aria-label', 'Saved app source, settings and secret values — only shown after explicit reveal');
      card.appendChild(settingsField);
    }
    const actions = node('div', undefined, 'adm-runner-job-actions');
    if (job.id) {
      actions.appendChild(button('Show & copy code, settings & saved secrets',
        (event) => revealJobSettings(job.id, settingsField, event.currentTarget)));
      const restart = button('Restart / recover this bot', async (event) => {
        const b = event.currentTarget;
        try {
          b.disabled = true; b.textContent = 'Restarting…';
          const result = await w.api(`/admin/jobs/${encodeURIComponent(job.id)}/restart`, 'POST', {}, true);
          if (typeof w.toast === 'function') w.toast(result.message || 'Restart requested.', 'success');
          await w.openAdminRunner(runnerId);
        } catch (e) {
          if (typeof w.toast === 'function') w.toast((w._admFriendlyErr && w._admFriendlyErr(e, 'Could not restart bot')) || e.message, 'error');
        } finally { b.disabled = false; b.textContent = 'Restart / recover this bot'; }
      });
      restart.disabled = !runner.online;
      restart.title = runner.online ? 'Restart on the runner that owns this job' : 'Runner is not answering; use Check / wake first.';
      actions.appendChild(restart);
      if (job.desired_state !== 'stopped') {
        const stop = button('Stop bot', async (event) => {
          if (!w.confirm('Stop this bot? Its files and database will be kept.')) return;
          const b = event.currentTarget;
          try {
            b.disabled = true; b.textContent = 'Stopping…';
            const result = await w.api(`/admin/jobs/${encodeURIComponent(job.id)}/stop`, 'POST', {}, true);
            if (typeof w.toast === 'function') w.toast(result.message || 'Bot stopped.', 'success');
            await w.openAdminRunner(runnerId);
          } catch (e) {
            if (typeof w.toast === 'function') w.toast((w._admFriendlyErr && w._admFriendlyErr(e, 'Could not stop bot')) || e.message, 'error');
          } finally { b.disabled = false; b.textContent = 'Stop bot'; }
        }, 'btn-ghost sm danger');
        stop.disabled = !runner.online;
        actions.appendChild(stop);
      }
    } else if (job.orphan) {
      actions.appendChild(node('span', 'No site job row; restart controls are unavailable until it is matched.', 'adm-hint'));
    }
    if (actions.childNodes.length) card.appendChild(actions);
    return card;
  }

  function renderRunner(data, body, id) {
    body.textContent = '';
    const runner = data.runner || {};
    const header = node('div', undefined, 'adm-runner-detail-summary');
    const status = node('span', runner.online ? 'online' : 'offline', `adm-pill${runner.online ? ' ok' : ' warn'}`);
    header.append(status,
      node('span', `${runner.enabled ? 'Taking new jobs' : 'Drained — no new placements'}`, 'adm-hint'),
      node('span', `Checked: ${runner.checked_at || '—'}`, 'adm-hint'));
    body.appendChild(header);

    const links = node('div', undefined, 'adm-runner-detail-links');
    const base = safeLink(runner.url, runner.url || 'Runner URL');
    const health = safeLink(runner.health_url, 'Open /health');
    if (base) links.appendChild(base);
    if (health) links.appendChild(health);
    if (links.childNodes.length) body.appendChild(links);
    body.appendChild(node('p', runner.reason || 'No diagnosis available.', `adm-runner-diagnosis${runner.online ? '' : ' warn'}`));
    if (runner.job_list_error) body.appendChild(node('p', runner.job_list_error, 'adm-runner-diagnosis warn'));

    const stats = node('div', undefined, 'adm-stats adm-runner-detail-stats');
    [[runner.jobs || 0, 'running on runner'], [runner.assigned_jobs || 0, 'assigned in site'],
      [`${runner.mem_mb || 0} / ${runner.safe_mb || 0}MB`, 'used / safe memory'],
      [`${runner.free_mb || 0}MB`, 'free memory']].forEach(([value, label]) => {
      const box = node('div', undefined, 'adm-stat');
      box.append(node('b', value), node('span', label)); stats.appendChild(box);
    });
    body.appendChild(stats);

    const actions = node('div', undefined, 'adm-runner-detail-actions');
    actions.appendChild(button('Check / wake + recover', () => w.wakeAdminRunner(id), 'btn-primary sm'));
    actions.appendChild(button('Show & copy saved runner settings', (event) => revealRunnerSettings(id, event.currentTarget)));
    body.appendChild(actions);
    const settings = node('textarea', undefined, 'input-text adm-runner-secret-settings');
    settings.id = 'admRunnerSecretSettings'; settings.readOnly = true; settings.rows = 3; settings.hidden = true;
    settings.setAttribute('aria-label', 'Saved runner URL and secret — only shown after explicit reveal');
    body.appendChild(settings);

    const jobs = data.jobs || [];
    body.appendChild(section(`Assigned jobs (${jobs.length})`, 'Open each app, see which URL/runner it uses, and restart or stop without signing into the job owner account.'));
    if (!jobs.length) body.appendChild(node('div', 'No site jobs are assigned to this runner.', 'adm-empty'));
    else {
      const grid = node('div', undefined, 'adm-runner-job-list');
      jobs.forEach(job => grid.appendChild(renderJobCard(job, runner, id)));
      body.appendChild(grid);
    }

    body.appendChild(section('What was done', 'Runner changes plus saved deploy/revision history; source code and bot-token values are not included.'));
    const history = data.history || [];
    if (!history.length) body.appendChild(node('div', 'No recorded runner/job actions yet.', 'adm-empty'));
    else {
      const list = node('ol', undefined, 'adm-runner-history');
      history.slice(0, 100).forEach(ev => {
        const labels = {
          admin_job_restart: 'Admin requested bot restart',
          admin_job_stop: 'Admin stopped bot',
          runner_wake_check: 'Runner health check / wake',
          runner_recovery_sweep: 'Recovery sweep',
          runner_secret_reveal: 'Runner settings revealed',
          admin_job_settings_reveal: 'Job settings revealed',
          'Automatic recovery succeeded': 'Automatic recovery succeeded',
          'Automatic recovery blocked': 'Automatic recovery blocked',
          'Automatic recovery failed': 'Automatic recovery failed'
        };
        const action = labels[ev.action] || String(ev.action || 'action').replace(/_/g, ' ');
        const who = ev.admin ? ` · ${ev.admin}` : (ev.actor === 'system' ? ' · automatic' : (ev.actor ? ` · ${ev.actor}` : ''));
        const target = ev.job_name ? ` · ${ev.job_name}${ev.job_id ? ` (#${ev.job_id})` : ''}` : '';
        const extra = ev.details ? ` · ${ev.details}` : (ev.target ? ` · ${ev.target}` : '');
        list.appendChild(node('li', `${ev.created_at || '—'} · ${action}${target}${who}${extra}`));
      });
      body.appendChild(list);
    }
    body.appendChild(node('p', data.setup && data.setup.note || '', 'adm-hint'));
  }

  async function openAdminRunner(id) {
    const modal = d.getElementById('admRunnerModal');
    const body = d.getElementById('admRunnerBody');
    const title = d.getElementById('admRunnerTitle');
    if (!modal || !body) return;
    observeModalClose(modal);
    _clearSecret();
    title.textContent = 'Loading runner…';
    body.textContent = '';
    if (typeof w.openModal === 'function') w.openModal('admRunnerModal');
    try {
      const data = await w.api(runnerApiPath(id), 'GET', null, true);
      const r = data.runner || {};
      title.textContent = `${r.label || 'Runner'}${r.id ? ` · #${r.id}` : ''}`;
      renderRunner(data, body, id);
    } catch (e) {
      title.textContent = 'Runner details';
      body.appendChild(node('div', (w._admFriendlyErr && w._admFriendlyErr(e, 'Could not load runner details')) || e.message, 'adm-empty'));
    }
  }

  async function wakeAdminRunner(id, buttonEl) {
    const b = buttonEl || null;
    const before = b ? b.textContent : '';
    try {
      if (b) { b.disabled = true; b.textContent = 'Checking runner…'; }
      const result = await w.api(runnerApiPath(id, 'wake'), 'POST', {}, true);
      if (typeof w.toast === 'function') w.toast(result.message || result.reason || 'Runner check finished.', result.ok ? 'success' : 'error');
      if (d.getElementById('admRunnerModal') && d.getElementById('admRunnerModal').classList.contains('open')) {
        await openAdminRunner(id);
      } else if (typeof w.loadAdminPanel === 'function') {
        await w.loadAdminPanel(true);
      }
    } catch (e) {
      if (typeof w.toast === 'function') w.toast((w._admFriendlyErr && w._admFriendlyErr(e, 'Runner check failed')) || e.message, 'error');
    } finally {
      if (b) { b.disabled = false; b.textContent = before || 'Check / wake + recover'; }
    }
  }

  w.openAdminRunner = openAdminRunner;
  w.wakeAdminRunner = wakeAdminRunner;
  w.revealAdminJobSettings = revealJobSettings;
  d.addEventListener('click', function (event) {
    if (event.target && event.target.closest && event.target.closest('#admRunnerModal [data-close]')) {
      setTimeout(_clearSecret, 0);
    }
  });
})(window, document);
