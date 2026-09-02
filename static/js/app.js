function shipmateApp() {
  const STORAGE_KEY = 'shipmate_session_id';

  return {
    sessionId: localStorage.getItem(STORAGE_KEY) || crypto.randomUUID(),
    repo: '',
    repoInput: '',
    context: null,
    liveStatus: null,
    activeStage: 'dev',
    activeView: 'fleet',
    terminal: '',
    terminalStatus: 'idle',
    commitMsg: '',
    checklist: { items: [], all_passed: false },
    activityOverview: [],
    activityProject: null,
    auditEntries: [],
    auditFilter: '',
    settings: null,
    secrets: { secrets: [] },
    secretsScope: 'project',
    secretName: '',
    secretValue: '',
    secretImport: '',
    modals: {
      identity: false,
      activity: false,
      settings: false,
      secrets: false,
      audit: false,
      repoChoice: false,
      discardCache: false,
      projectForm: false,
    },
    fleetProjects: [],
    fleetInspections: [],
    fleetLoading: false,
    expandedFleetId: null,
    projectForm: {
      project_id: '',
      name: '',
      stack: '',
      remote_url: '',
      dev_path: '',
      qa_path: '',
      prod_ssh_host: '',
      prod_remote_path: '',
      health_url: '',
      provider: 'oracle_vm',
    },
    editingProjectId: null,
    repoChoice: { matches: [], remote: '', branch: null },
    branchList: [],
    selectedBranch: '',
    identityName: '',
    identityEmail: '',
    loading: false,
    error: '',

    stages: [
      { id: 'dev', label: 'Stage 1: Dev', subtitle: 'Windows • Pre-flight & PR' },
      { id: 'qa', label: 'Stage 2: QA', subtitle: 'Linux • Test Suites & Smoke' },
      { id: 'prod', label: 'Stage 3: Prod', subtitle: 'Live Deploy' },
    ],

    init() {
      localStorage.setItem(STORAGE_KEY, this.sessionId);
      this.repo = localStorage.getItem('shipmate_repo') || '';
      this.repoInput = this.repo;
      this.openFleet();
    },

    headers() {
      return { 'Content-Type': 'application/json', 'X-Session-Id': this.sessionId };
    },

    async api(path, options = {}) {
      const res = await fetch(path, { ...options, headers: { ...this.headers(), ...options.headers } });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        const msg = err.detail || err.error || 'Request failed';
        if (res.status === 404 && path.includes('/api/projects')) {
          throw new Error('Fleet API not available — restart the server (python start.py) to load the latest code.');
        }
        throw new Error(msg);
      }
      return res.json();
    },

    isRemoteInput(value) {
      const v = (value || '').trim();
      return /^(https?:\/\/|git@|ssh:\/\/)/.test(v) || /^[\w.-]+@[\w.-]+:/.test(v);
    },

    async loadContext() {
      if (!this.repo) return;
      this.loading = true;
      this.error = '';
      try {
        this.context = await this.api(`/api/context?repo=${encodeURIComponent(this.repo)}`);
        this.identityName = this.context.identity.name;
        this.identityEmail = this.context.identity.email;
        this.liveStatus = await this.api(`/api/live-status?repo=${encodeURIComponent(this.repo)}`);
        const prodStage = this.stages.find(s => s.id === 'prod');
        if (prodStage) prodStage.subtitle = `${this.context.provider_label} • Live Deploy`;
        await this.loadChecklist();
      } catch (e) {
        this.error = e.message;
        this.context = null;
      } finally {
        this.loading = false;
      }
    },

    async fetchBranches() {
      const input = this.repoInput.trim();
      if (!this.isRemoteInput(input)) {
        this.branchList = [];
        return;
      }
      try {
        const data = await this.api('/api/repo/branches', {
          method: 'POST',
          body: JSON.stringify({ repo: input }),
        });
        this.branchList = data.branches || [];
        if (this.branchList.length && !this.selectedBranch) {
          this.selectedBranch = this.branchList.includes('main')
            ? 'main'
            : this.branchList.includes('master')
              ? 'master'
              : this.branchList[0];
        }
      } catch {
        this.branchList = [];
      }
    },

    async syncRepo(mode = 'auto', localPath = null) {
      const input = this.repoInput.trim();
      if (!input) return;
      this.loading = true;
      this.error = '';
      try {
        if (this.isRemoteInput(input) && mode === 'auto') {
          const discovery = await this.api('/api/repo/discover', {
            method: 'POST',
            body: JSON.stringify({ repo: input }),
          });
          if (discovery.status === 'needs_choice') {
            this.repoChoice = {
              matches: discovery.matches || [],
              remote: discovery.remote,
              branch: discovery.branch,
            };
            this.modals.repoChoice = true;
            this.loading = false;
            return;
          }
          mode = 'cache';
        }

        const sync = await this.api('/api/repo/sync', {
          method: 'POST',
          body: JSON.stringify({
            repo: input,
            mode,
            local_path: localPath,
            branch: this.selectedBranch || null,
          }),
        });

        if (sync.status === 'needs_choice') {
          this.repoChoice = {
            matches: sync.matches || [],
            remote: sync.remote,
            branch: sync.branch,
          };
          this.modals.repoChoice = true;
          return;
        }
        if (!sync.valid) throw new Error(sync.message);

        this.repo = sync.repo;
        this.repoInput = sync.repo;
        localStorage.setItem('shipmate_repo', this.repo);
        if (sync.branches?.length) this.branchList = sync.branches;
        if (sync.branch) this.selectedBranch = sync.branch;
        await this.loadContext();
      } catch (e) {
        this.error = e.message;
        this.context = null;
      } finally {
        this.loading = false;
      }
    },

    async chooseLocalWorkspace(match) {
      this.modals.repoChoice = false;
      await this.syncRepo('local', match.path);
    },

    async chooseCacheWorkspace() {
      this.modals.repoChoice = false;
      await this.syncRepo('cache');
    },

    async onBranchChange() {
      if (!this.isRemoteInput(this.repoInput) || !this.selectedBranch) return;
      await this.syncRepo('cache');
    },

    async discardCacheChanges() {
      this.modals.discardCache = false;
      this.loading = true;
      this.error = '';
      try {
        await this.api('/api/repo/discard-cache', {
          method: 'POST',
          body: JSON.stringify({ repo: this.repo, confirm: true }),
        });
        await this.loadContext();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    modeBadgeLabel() {
      if (!this.context) return '';
      const mode = this.context.repo_mode || 'local';
      const path = this.context.path_display || this.repo;
      return mode === 'cache' ? `Managed Cache: ${path}` : `Local Workspace: ${path}`;
    },

    modeBadgeClass() {
      const wt = this.context?.working_tree;
      if (!wt || wt.clean) return 'pill-emerald';
      return 'pill-amber';
    },

    dirtySummary() {
      const wt = this.context?.working_tree;
      if (!wt || wt.clean) return '';
      const parts = [];
      if (wt.modified) parts.push(`${wt.modified} modified`);
      if (wt.untracked) parts.push(`${wt.untracked} untracked`);
      if (wt.staged) parts.push(`${wt.staged} staged`);
      return parts.join(', ');
    },

    matchDirtySummary(match) {
      const wt = match.working_tree;
      if (!wt || wt.clean) return 'clean';
      const parts = [];
      if (wt.modified) parts.push(`${wt.modified} modified`);
      if (wt.untracked) parts.push(`${wt.untracked} untracked`);
      return parts.join(', ') || 'dirty';
    },

    showDiscardButton() {
      return this.context?.repo_mode === 'cache' && this.context?.working_tree && !this.context.working_tree.clean;
    },

    async loadChecklist() {
      if (!this.repo || this.activeView !== 'pipeline') return;
      this.checklist = await this.api(
        `/api/checklist?repo=${encodeURIComponent(this.repo)}&stage=${this.activeStage}`
      );
    },

    selectStage(stage) {
      this.activeStage = stage;
      this.activeView = 'pipeline';
      this.loadChecklist();
    },

    stageStatus(stage) {
      return this.context?.stage_statuses?.[stage] || 'pending';
    },

    stageCardClass(stage) {
      const s = this.stageStatus(stage);
      let cls = 'stage-card mb-3';
      if (this.activeStage === stage && this.activeView === 'pipeline') cls += ' active';
      if (s === 'passed') cls += ' passed';
      return cls;
    },

    statusBadge(stage) {
      const map = { pending: 'badge-pending', in_progress: 'badge-progress', passed: 'badge-passed', failed: 'badge-failed' };
      return map[this.stageStatus(stage)] || 'badge-pending';
    },

    statusLabel(stage) {
      const map = { pending: 'PENDING', in_progress: 'ACTIVE', passed: 'PASSED', failed: 'FAILED' };
      return map[this.stageStatus(stage)] || 'PENDING';
    },

    isStageEnabled(stage) {
      if (!this.context) return false;
      if (stage === this.context.primary_stage) return true;
      return this.context.host_overrides?.[stage] || false;
    },

    async toggleHostOverride(stage, enabled) {
      await this.api('/api/host-override', {
        method: 'POST',
        body: JSON.stringify({ repo: this.repo, stage, enabled }),
      });
      await this.loadContext();
    },

    async toggleChecklistItem(item) {
      if (item.type !== 'manual') return;
      await this.api('/api/checklist/manual', {
        method: 'PATCH',
        body: JSON.stringify({ repo: this.repo, item_id: item.id, checked: !item.checked }),
      });
      await this.loadChecklist();
      await this.loadContext();
    },

    async runJob(url, body) {
      this.terminal = '';
      this.terminalStatus = 'busy';
      try {
        const { job_id } = await this.api(url, { method: 'POST', body: JSON.stringify(body) });
        await new Promise((resolve, reject) => {
          const ws = new WebSocket(`ws://${location.host}/ws/jobs/${job_id}`);
          ws.onmessage = (ev) => {
            const data = JSON.parse(ev.data);
            if (data.type === 'line') this.terminal += data.text;
            if (data.type === 'done') {
              this.terminalStatus = data.success ? 'idle' : 'error';
              if (data.message) this.terminal += `\n→ ${data.message}\n`;
              ws.close();
              data.success ? resolve(data) : reject(new Error(data.message));
            }
          };
          ws.onerror = () => reject(new Error('WebSocket error'));
        });
        await this.loadContext();
        await this.loadChecklist();
      } catch (e) {
        this.terminalStatus = 'error';
        this.terminal += `\nERROR: ${e.message}\n`;
      }
    },

    async devShip() {
      await this.runJob('/api/stages/dev/ship', {
        repo: this.repo,
        commit_msg: this.commitMsg,
        host_override: this.context.host_overrides?.dev || false,
      });
    },

    async qaAction(action) {
      await this.runJob(`/api/stages/qa/${action}`, {
        repo: this.repo,
        host_override: this.context.host_overrides?.qa || false,
      });
    },

    async prodAction(action, checkId = null) {
      await this.runJob(`/api/stages/prod/${action}`, {
        repo: this.repo,
        host_override: this.context.host_overrides?.prod || false,
        check_id: checkId,
      });
    },

    async saveIdentity() {
      await this.api('/api/identity/override', {
        method: 'POST',
        body: JSON.stringify({ repo: this.repo, name: this.identityName, email: this.identityEmail }),
      });
      this.modals.identity = false;
      await this.loadContext();
    },

    async openActivity() {
      if (!this.repo) {
        this.error = 'Sync a repo first to view activity.';
        return;
      }
      this.activeView = 'activity';
      this.activityOverview = await this.api('/api/activity/overview');
      this.activityProject = await this.api(`/api/activity/project?repo=${encodeURIComponent(this.repo)}`);
    },

    async openSettings() {
      if (!this.repo) {
        this.error = 'Sync a repo first to view settings.';
        return;
      }
      this.activeView = 'settings';
      this.settings = await this.api(`/api/settings/deploy?repo=${encodeURIComponent(this.repo)}`);
    },

    async openSecrets() {
      if (!this.repo) {
        this.secretsScope = 'global';
      }
      this.activeView = 'secrets';
      this.error = '';
      await this.loadSecrets();
    },

    async setSecretsScope(scope) {
      if (scope === 'project' && !this.repo) {
        this.error = 'Open a project from Fleet to manage project-specific secrets.';
        return;
      }
      this.secretsScope = scope;
      await this.loadSecrets();
    },

    secretsGoBack() {
      this.activeView = this.context ? 'pipeline' : 'fleet';
    },

    async loadSecrets() {
      const scope = this.secretsScope === 'project' ? 'project' : 'global';
      const repo = scope === 'project' ? this.repo : null;
      const q = repo ? `scope=${scope}&repo=${encodeURIComponent(repo)}` : `scope=${scope}`;
      this.secrets = await this.api(`/api/secrets?${q}`);
    },

    async saveSecret() {
      await this.api('/api/secrets', {
        method: 'POST',
        body: JSON.stringify({
          scope: this.secretsScope === 'project' ? 'project' : 'global',
          repo: this.secretsScope === 'project' ? this.repo : null,
          name: this.secretName,
          value: this.secretValue,
        }),
      });
      this.secretName = '';
      this.secretValue = '';
      await this.loadSecrets();
    },

    async deleteSecret(name) {
      await this.api('/api/secrets/delete', {
        method: 'POST',
        body: JSON.stringify({
          scope: this.secretsScope === 'project' ? 'project' : 'global',
          repo: this.secretsScope === 'project' ? this.repo : null,
          name,
        }),
      });
      await this.loadSecrets();
    },

    async importSecrets() {
      const count = await this.api('/api/secrets/import', {
        method: 'POST',
        body: JSON.stringify({
          scope: this.secretsScope === 'project' ? 'project' : 'global',
          repo: this.secretsScope === 'project' ? this.repo : null,
          env_content: this.secretImport,
        }),
      });
      this.secretImport = '';
      alert(`Imported ${count.count} secrets`);
      await this.loadSecrets();
    },

    async openAudit() {
      this.modals.audit = true;
      await this.loadAudit();
    },

    async loadAudit() {
      this.auditEntries = await this.api(`/api/audit?filter=${encodeURIComponent(this.auditFilter)}`);
    },

    liveStatusLabel() {
      if (!this.liveStatus) return 'Checking...';
      if (this.liveStatus.latency_ms) return `${this.liveStatus.label} • ${this.liveStatus.latency_ms}ms`;
      return this.liveStatus.label;
    },

    builtinChecked(id) {
      return this.context?.session?.checklist_builtin?.[id] || false;
    },

    emptyProjectForm() {
      return {
        project_id: '',
        name: '',
        stack: '',
        remote_url: '',
        dev_path: '',
        qa_path: '',
        prod_ssh_host: '',
        prod_remote_path: '',
        health_url: '',
        provider: 'oracle_vm',
      };
    },

    async openFleet() {
      this.activeView = 'fleet';
      this.expandedFleetId = null;
      await this.loadFleet();
    },

    openPipeline() {
      this.activeView = 'pipeline';
      this.error = '';
    },

    toggleFleetExpand(projectId) {
      this.expandedFleetId = this.expandedFleetId === projectId ? null : projectId;
    },

    isFleetExpanded(projectId) {
      return this.expandedFleetId === projectId;
    },

    formatLastUsed(iso) {
      if (!iso) return '';
      try {
        return new Date(iso).toLocaleString();
      } catch {
        return '';
      }
    },

    async loadFleet() {
      this.fleetLoading = true;
      this.error = '';
      try {
        const data = await this.api('/api/projects');
        this.fleetProjects = data.projects || [];
        this.fleetInspections = [];
        if (this.fleetProjects.length) {
          try {
            await this.refreshFleet(false);
          } catch (inspectErr) {
            this.error = `Projects loaded (${this.fleetProjects.length}), but inspection failed: ${inspectErr.message}`;
          }
        }
      } catch (e) {
        this.error = e.message;
        this.fleetProjects = [];
        this.fleetInspections = [];
      } finally {
        this.fleetLoading = false;
      }
    },

    async refreshFleet(bypassCache = true) {
      this.fleetLoading = true;
      this.error = '';
      try {
        if (!this.fleetProjects.length) {
          const data = await this.api('/api/projects');
          this.fleetProjects = data.projects || [];
        }
        const data = await this.api('/api/projects/inspect', {
          method: 'POST',
          body: JSON.stringify({ bypass_cache: bypassCache }),
        });
        this.fleetInspections = data.inspections || [];
      } catch (e) {
        this.error = e.message;
      } finally {
        this.fleetLoading = false;
      }
    },

    fleetInspection(projectId) {
      return this.fleetInspections.find(i => i.project_id === projectId) || null;
    },

    tierStatusClass(status) {
      const ok = ['clean', 'synced', 'ok', 'merged', 'pr_open'];
      const warn = ['dirty', 'ahead', 'behind', 'manual_test', 'pr_open'];
      if (ok.includes(status)) return 'pill-emerald';
      if (warn.includes(status)) return 'pill-amber';
      return 'pill-rose';
    },

    tierStatusLabel(status) {
      const map = {
        clean: 'Clean',
        dirty: 'Dirty',
        synced: 'Synced',
        ahead: 'Ahead',
        behind: 'Behind',
        ok: 'OK',
        timeout: 'Timeout',
        unreachable: 'Unreachable',
        pr_open: 'PR Open',
        merged: 'Merged',
        manual_test: 'Manual Test',
      };
      return map[status] || status || 'Unknown';
    },

    openProjectModal(project = null) {
      if (project) {
        this.editingProjectId = project.project_id;
        this.projectForm = { ...this.emptyProjectForm(), ...project };
      } else {
        this.editingProjectId = null;
        this.projectForm = this.emptyProjectForm();
      }
      this.modals.projectForm = true;
    },

    async autoPopulateProjectFromRepo() {
      const path = this.context?.repo || this.repoInput.trim();
      if (!path) return;
      try {
        const data = await this.api('/api/projects/auto-populate', {
          method: 'POST',
          body: JSON.stringify({ path }),
        });
        this.projectForm = { ...this.emptyProjectForm(), ...data.draft };
      } catch (e) {
        this.error = e.message;
      }
    },

    async importRegisteredProjects() {
      try {
        const data = await this.api('/api/projects/import-registered', { method: 'POST' });
        await this.loadFleet();
        alert(`Imported ${data.imported} project(s)`);
      } catch (e) {
        this.error = e.message;
      }
    },

    async saveProject() {
      try {
        if (this.editingProjectId) {
          await this.api(`/api/projects/${this.editingProjectId}`, {
            method: 'PUT',
            body: JSON.stringify(this.projectForm),
          });
        } else {
          await this.api('/api/projects', {
            method: 'POST',
            body: JSON.stringify(this.projectForm),
          });
        }
        this.modals.projectForm = false;
        await this.loadFleet();
      } catch (e) {
        this.error = e.message;
      }
    },

    async deleteProject(projectId) {
      if (!confirm('Remove this project from the fleet registry?')) return;
      try {
        await this.api(`/api/projects/${projectId}`, { method: 'DELETE' });
        await this.loadFleet();
      } catch (e) {
        this.error = e.message;
      }
    },

    async openProjectFromFleet(project) {
      try {
        const data = await this.api(`/api/projects/${project.project_id}/touch`, { method: 'POST' });
        const touched = data.project;
        this.fleetProjects = [
          touched,
          ...this.fleetProjects.filter(p => p.project_id !== project.project_id),
        ];
      } catch (e) {
        this.error = e.message;
      }
      const repo = project.dev_path || project.qa_path || project.remote_url;
      this.repoInput = repo;
      this.activeView = 'pipeline';
      if (project.dev_path) {
        this.repo = project.dev_path;
        localStorage.setItem('shipmate_repo', project.dev_path);
        await this.loadContext();
      } else {
        await this.syncRepo();
      }
    },

    fleetSuggestionAction(inspection) {
      const action = inspection?.suggestion?.action || '';
      if (action.startsWith('stage_') || action === 'dev_ship') {
        this.activeStage = 'dev';
      } else if (action.startsWith('qa')) {
        this.activeStage = 'qa';
      } else if (action.startsWith('prod')) {
        this.activeStage = 'prod';
      }
      const project = this.fleetProjects.find(p => p.project_id === inspection.project_id);
      if (project) this.openProjectFromFleet(project);
    },
  };
}
