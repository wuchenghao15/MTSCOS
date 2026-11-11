/* ============================================================================
 * theme-manager.js — MTSCOS 冰山主题矩阵前端调度器
 * v1.0.0 · 30年金牌美工团出品
 * ============================================================================
 * 职责:
 *   1. 主题切换 — localStorage 持久化 + body[data-theme] 属性注入
 *   2. 深浅切换 — body[data-dark="0|1"] 属性注入
 *   3. 节日自动触发 — 公祭日/佛教日/春节/清明/中秋 检测 → 自动切主题
 *   4. 角色锁 — SA页锁sa主题, admin页锁admin主题 (同 theme_routes.py)
 *   5. 页面锁 — 特定页面强制特定主题
 *
 * 主题矩阵 (14 套):
 *   基础: 青瓷卷(default) / 青瓷黛(dark) / 极光(aurora) / 暮光(twilight) / 晨曦(dawn) / 墨韵(ink)
 *   扩展: 冰山(iceberg) / SA(sa) / Admin(admin) / 公祭日(memorial) / 佛教日(buddhist) / 春节(spring) / 护眼(eye-care)
 *   系统: 和青瓷卷同 (默认浅色)
 *
 * 优先级链 (同 theme_routes.py §5):
 *   PAGE_LOCK (0) > FESTIVAL (1) > USER_PREF (2) > DEFAULT (3)
 * ============================================================================ */
(function(){
  'use strict';

  const STORAGE_KEY = 'mtscos_theme_prefs_v1';
  const THEMES = ['iceberg','sa','admin','memorial','buddhist','spring','eye-care','aurora','twilight','dawn','ink','dark','default'];

  /* ── §1 节日日历 (2026-2027 农历节日近似) ── */
  const FESTIVAL_MAP = [
    // 公祭日
    { theme: 'memorial',  month: 12,  day: 13,  label: '南京大屠杀死难者国家公祭日' },
    { theme: 'memorial',  month: 9,   day: 3,   label: '中国人民抗日战争胜利纪念日' },
    { theme: 'memorial',  month: 5,   day: 12,  label: '全国防灾减灾日' },
    { theme: 'memorial',  month: 4,   day: 5,   label: '清明节' },
    // 春节 (农历正月初一 → 2026/2/17, 2027/2/6)
    { theme: 'spring',    month: 2,   day: 17,  year: 2026, label: '春节' },
    { theme: 'spring',    month: 2,   day: 6,   year: 2027, label: '春节' },
    // 佛教日
    { theme: 'buddhist',  month: 4,   day: 26,  label: '释迦牟尼佛诞日 (浴佛节)' },
    { theme: 'buddhist',  month: 7,   day: 30,  label: '地藏王菩萨诞日' },
    { theme: 'buddhist',  month: 11,  day: 17,  label: '阿弥陀佛诞日' },
    { theme: 'buddhist',  month: 2,   day: 15,  label: '观音菩萨成道日' },
  ];

  /* ── §2 页面锁 (强制主题) ── */
  const PAGE_LOCK = {
    '/sa/':         'sa',
    '/admin_app/':  'admin',
    '/admin/':      'admin',
    '/rules':       'admin',
    '/permissions': 'admin',
    '/auth/':       'iceberg',
    '/login':       'iceberg',
  };

  /* ── §3 核心引擎 ── */
  const ThemeManager = {
    prefs: { theme: 'default', dark: 0, user_picked: false },

    init() {
      this._loadPrefs();
      const finalTheme = this._resolveFinalTheme();
      this._applyTheme(finalTheme);
      this._applyDark(this.prefs.dark);
      this._injectSwitcher();
      this._bindGlobalShortcuts();
      document.dispatchEvent(new CustomEvent('theme-ready', { detail: { theme: finalTheme, dark: this.prefs.dark } }));
    },

    _loadPrefs() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
          this.prefs = Object.assign({}, this.prefs, JSON.parse(raw));
          return;
        }
        // 🔄 兼容迁移:旧 key → 新 key
        const oldMtscosTheme = localStorage.getItem('mtscos-theme');       // base.html 旧极简脚本
        const oldArtTheme    = localStorage.getItem('art-theme');         // gallery base_layout.html
        const oldIcebergTheme= localStorage.getItem('iceberg-theme');      // andromeda center 旧
        const oldKey         = localStorage.getItem('theme-prefs');       // 更旧的通用名
        let migrated = oldMtscosTheme || oldArtTheme || oldIcebergTheme || oldKey;
        if (migrated) {
          // 旧 key 的 theme 值可能是 andromeda / andromeda-dark / porcelain → 归一化
          const aliasMap = {
            'andromeda':     'default',
            'andromeda-dark':'dark',
            'porcelain':     'default',
          };
          let t = aliasMap[migrated] || migrated;
          if (!THEMES.includes(t)) t = 'default';
          this.prefs.theme = t;
          this.prefs.user_picked = true;
          localStorage.setItem(STORAGE_KEY, JSON.stringify(this.prefs));
          // 清理旧 key
          ['mtscos-theme','art-theme','iceberg-theme','theme-prefs'].forEach(k=>localStorage.removeItem(k));
        }
      } catch(e) {}
    },

    _savePrefs() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.prefs));
    },

    _resolveFinalTheme() {
      const path = location.pathname;
      // 优先级 0: PAGE_LOCK
      for (const [prefix, t] of Object.entries(PAGE_LOCK)) {
        if (path.startsWith(prefix)) return t;
      }
      // 优先级 1: FESTIVAL
      const today = new Date();
      const festival = FESTIVAL_MAP.find(f => {
        if (f.year && f.year !== today.getFullYear()) return false;
        return f.month === today.getMonth()+1 && f.day === today.getDate();
      });
      if (festival) {
        this.prefs.festival_lock = festival.theme;
        return festival.theme;
      }
      this.prefs.festival_lock = null;
      // 优先级 2: USER_PREF
      if (this.prefs.theme && this.prefs.theme !== 'default') return this.prefs.theme;
      return 'default';
    },

    _applyTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      document.body.setAttribute('data-theme', theme);
    },

    _applyDark(dark) {
      document.documentElement.setAttribute('data-dark', dark ? '1' : '0');
      document.body.setAttribute('data-dark', dark ? '1' : '0');
    },

    /* ── §4 公开 API ── */
    setTheme(theme) {
      if (!THEMES.includes(theme)) return false;
      this.prefs.theme = theme;
      this.prefs.user_picked = true;
      this._savePrefs();
      this._applyTheme(theme);
      document.dispatchEvent(new CustomEvent('theme-change', { detail: { theme } }));
      return true;
    },

    toggleDark() {
      this.prefs.dark = this.prefs.dark ? 0 : 1;
      this._savePrefs();
      this._applyDark(this.prefs.dark);
      document.dispatchEvent(new CustomEvent('dark-toggle', { detail: { dark: this.prefs.dark } }));
    },

    getFestivals(range_days) {
      const today = new Date();
      const end = new Date(today.getTime() + range_days * 86400000);
      return FESTIVAL_MAP.filter(f => {
        if (f.year && (f.year < today.getFullYear() || f.year > end.getFullYear())) return false;
        let d = new Date(f.year || today.getFullYear(), f.month-1, f.day);
        return d >= new Date(today.getFullYear(), today.getMonth(), today.getDate()) && d <= end;
      });
    },

    /* ── §5 悬浮切换器 ── */
    _injectSwitcher() {
      if (document.getElementById('mtscos-theme-switcher')) return;
      const panel = document.createElement('div');
      panel.id = 'mtscos-theme-switcher';
      panel.innerHTML = `
        <style>
          #mtscos-theme-switcher {
            position: fixed; bottom: 20px; right: 20px; z-index: 9999;
            font-family: var(--mtscos-font-sans, -apple-system, sans-serif);
          }
          #mtscos-theme-btn {
            width: 42px; height: 42px; border-radius: 50%;
            background: var(--mtscos-bg-card, #fff);
            border: 1px solid var(--mtscos-border-strong, #ddd);
            box-shadow: var(--mtscos-shadow-lg, 0 8px 24px rgba(0,0,0,.15));
            cursor: pointer; font-size: 18px;
            display: flex; align-items: center; justify-content: center;
            transition: transform .2s;
          }
          #mtscos-theme-btn:hover { transform: scale(1.05); }
          #mtscos-theme-panel {
            display: none; position: absolute; bottom: 52px; right: 0;
            width: 240px; padding: 14px;
            background: var(--mtscos-bg-card, #fff);
            border: 1px solid var(--mtscos-border-base, #ddd);
            border-radius: 10px;
            box-shadow: var(--mtscos-shadow-xl, 0 16px 40px rgba(0,0,0,.2));
            max-height: 360px; overflow-y: auto;
          }
          #mtscos-theme-panel.open { display: block; }
          .mtscos-tp-title {
            font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
            color: var(--mtscos-text-secondary, #888);
            margin-bottom: 8px; font-weight: 600;
          }
          .mtscos-tp-row {
            display: flex; align-items: center; gap: 8px;
            padding: 8px 10px; margin-bottom: 4px;
            border-radius: 6px; cursor: pointer;
            font-size: 12px;
            color: var(--mtscos-text-primary, #333);
            transition: background .15s;
          }
          .mtscos-tp-row:hover { background: var(--mtscos-primary-soft, rgba(0,100,255,.08)); }
          .mtscos-tp-row.active { background: var(--mtscos-primary-soft, rgba(0,100,255,.12)); font-weight: 600; }
          .mtscos-tp-swatch {
            width: 16px; height: 16px; border-radius: 4px; border: 1px solid rgba(0,0,0,.1);
            flex-shrink: 0;
          }
          .mtscos-tp-dark-btn {
            width: 100%; padding: 8px; margin-top: 10px;
            background: var(--mtscos-fill-base, #f0f0f0);
            border: 1px solid var(--mtscos-border-base, #ddd);
            border-radius: 6px; cursor: pointer;
            font-size: 11px; letter-spacing: 1px;
          }
          .mtscos-tp-festival {
            margin-top: 8px; padding-top: 8px;
            border-top: 1px dashed var(--mtscos-border-base, #ddd);
            font-size: 10px; color: var(--mtscos-text-secondary, #888);
          }
        </style>
        <div id="mtscos-theme-panel">
          <div class="mtscos-tp-title">主题切换</div>
          <div id="mtscos-tp-list"></div>
          <button class="mtscos-tp-dark-btn" id="mtscos-tp-dark">🌙 深色 / 浅色 (D)</button>
          <div class="mtscos-tp-festival" id="mtscos-tp-festival"></div>
        </div>
        <button id="mtscos-theme-btn" title="主题切换 (T)">🎨</button>
      `;
      document.body.appendChild(panel);

      const THEMES_META = [
        { id: 'default',    name: '青瓷卷 · 默认浅', swatch: 'linear-gradient(135deg,#5B8FB9,#6FA88B)' },
        { id: 'iceberg',    name: '冰山 · Andromeda', swatch: 'linear-gradient(135deg,#7C3AED,#2E86DE)' },
        { id: 'sa',         name: 'SA · 安全审计', swatch: 'linear-gradient(135deg,#2D5A5C,#B91C1C)' },
        { id: 'admin',      name: 'Admin · 系统管理', swatch: 'linear-gradient(135deg,#1E3A5F,#C9A961)' },
        { id: 'memorial',   name: '公祭日 · 黑白灰', swatch: 'linear-gradient(135deg,#2C2C2C,#8B0000)' },
        { id: 'buddhist',   name: '佛教日 · 禅金', swatch: 'linear-gradient(135deg,#D4A84B,#8B7355)' },
        { id: 'spring',     name: '春节 · 朱砂红', swatch: 'linear-gradient(135deg,#C41E3A,#D4A84B)' },
        { id: 'eye-care',   name: '护眼 · 柔绿', swatch: 'linear-gradient(135deg,#6B8E7B,#8FAE9D)' },
        { id: 'aurora',     name: '极光', swatch: 'linear-gradient(135deg,#409eff,#10b981)' },
        { id: 'twilight',   name: '暮光', swatch: 'linear-gradient(135deg,#8b5cf6,#ec4899)' },
        { id: 'dawn',       name: '晨曦', swatch: 'linear-gradient(135deg,#f97316,#fbbf24)' },
        { id: 'ink',        name: '墨韵', swatch: 'linear-gradient(135deg,#1a1a2e,#16213e)' },
      ];

      const list = panel.querySelector('#mtscos-tp-list');
      THEMES_META.forEach(t => {
        const row = document.createElement('div');
        row.className = 'mtscos-tp-row';
        row.dataset.theme = t.id;
        row.innerHTML = `<div class="mtscos-tp-swatch" style="background:${t.swatch}"></div>${t.name}`;
        row.addEventListener('click', () => {
          this.setTheme(t.id);
          this._refreshSwitcher();
        });
        list.appendChild(row);
      });

      panel.querySelector('#mtscos-theme-btn').addEventListener('click', () => {
        panel.querySelector('#mtscos-theme-panel').classList.toggle('open');
        this._refreshSwitcher();
      });

      panel.querySelector('#mtscos-tp-dark').addEventListener('click', () => {
        this.toggleDark();
        this._refreshSwitcher();
      });

      this._refreshSwitcher();
    },

    _refreshSwitcher() {
      const list = document.querySelectorAll('#mtscos-tp-list .mtscos-tp-row');
      list.forEach(row => row.classList.toggle('active', row.dataset.theme === (document.body.getAttribute('data-theme') || 'default')));
      // 节日提示
      const fEl = document.getElementById('mtscos-tp-festival');
      if (!fEl) return;
      const upcoming = this.getFestivals(30);
      if (upcoming.length) {
        fEl.textContent = `📅 最近节日: ${upcoming[0].label} (${upcoming[0].month}/${upcoming[0].day}) → 自动切换`;
      } else {
        fEl.textContent = '';
      }
      // 深浅按钮文案
      const darkBtn = document.getElementById('mtscos-tp-dark');
      if (darkBtn) {
        darkBtn.textContent = (document.body.getAttribute('data-dark') === '1') ? '☀️ 浅色模式 (D)' : '🌙 深色模式 (D)';
      }
    },

    _bindGlobalShortcuts() {
      document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.key === 't' || e.key === 'T') {
          e.preventDefault();
          const btn = document.getElementById('mtscos-theme-btn');
          if (btn) btn.click();
        } else if (e.key === 'd' || e.key === 'D') {
          e.preventDefault();
          this.toggleDark();
          this._refreshSwitcher();
        }
      });
    }
  };

  // 自动初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => ThemeManager.init());
  } else {
    ThemeManager.init();
  }

  window.ThemeManager = ThemeManager;
})();
