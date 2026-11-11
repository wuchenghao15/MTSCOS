/* MTSCOS AI · Global i18n (青瓷卷主题 · 4 语)
 * -----------------------------------------------------------------------------
 *   v1.0.0  ·  全站所有 HTML 页面经由 Flask after_request 自动注入 <script src="/static/i18n/i18n.js">
 *
 *   设计原则：
 *    1) 幂等 (Idempotent)：首页 index.html 已有内联 initLangModal 不会冲突。
 *    2) 自动装配 (ensureLangUIOnce)：页面没有 header-lang 按钮 -> 注入右下角 FAB；
 *       页面没有 #lang-modal -> 在 </body> 后 append 模态 DOM。
 *    3) 原文快照 (data-i18n-orig)：TreeWalker 扫描后快照，切换多次不漂移。
 *    4) 空白归一 (_normWs)：&nbsp; 全半角 Tab 多空格 -> 单空格，兼容window.t('auto.i18n.x_x_e43613ca') || '登 录'等变形。
 *    5) 图标安全 (translateElement)：按钮内含 <i>/<svg> 时，仅替换"最长 TEXT_NODE"。
 *    6) 可编辑保护：不修改 INPUT/TEXTAREA 的 value（除非明确走 data-i18n placeholder 路径）。
 * -------------------------------------------------------------------------- */
(function () {
  'use strict';
  if (window.__MTSCOS_I18N_LOADED__) return;   // 幂等：防止 after_request 与首页内联双加载
  window.__MTSCOS_I18N_LOADED__ = true;

  /*  仙女座 AI 修复 — window.t 安全壳
   * 根因: 模块顶层常量 LANGS/DICT 在 IIFE 初始化阶段就调用 _t(),
   *       但 window.t 要等 Flask after_request 或其他 i18n 库注入, 时序上还不存在.
   * 修复: 用 _t() 代替裸 _t() — t 存在就用 t(key), 不存在就返回 key 本身.
   *       翻译兜底靠后面的 || '简体中文' 等 fallback 字面量.
   * 2026-09-24 by 仙女座 AI
   */
  var _t = function (key) {
    try {
      var fn = window.t;
      if (typeof fn === 'function') {
        var v = fn(key);
        if (v && v !== key) return v;   // 翻译有值且不是 key 本身 -> 用翻译
      }
      // window.t 不存在或返回 key 本身 -> 返回空串, 让后面的 || fallback 生效
      return '';
    } catch (e) { return ''; }
  };

  /* ========== LANGS / DICT / KEY_ALIASES  （与 index.html 内联一致，后续字典更新统一改此处）========== */
  var LANGS = [
    { code: 'zh-CN', label: _t('auto.i18n.x_d688a3a4') || _t('auto.i18n.x_d688a3a4') || _t('auto.i18n.x_d688a3a4') || '简体中文', flag: 'ZH', tip: _t('auto.i18n.x_04c680d5') || _t('auto.i18n.x_04c680d5') || _t('auto.i18n.x_04c680d5') || '默认界面语言', short: '中' },
    { code: 'zh-TW', label: _t('auto.i18n.x_46c49965') || _t('auto.i18n.x_46c49965') || _t('auto.i18n.x_46c49965') || '繁體中文', flag: 'TW', tip: _t('auto.i18n.x_c0f0e1c9') || _t('auto.i18n.x_c0f0e1c9') || '繁體中文介面',   short: '繁' },
    { code: 'en-US', label: 'English',  flag: 'EN', tip: 'English (US)',     short: 'EN' },
    { code: 'ja-JP', label: _t('auto.i18n.x_00110af8') || '日本語',   flag: 'JA', tip: _t('auto.i18n.x_________d793c18b') || _t('auto.i18n.x_________d793c18b') || _t('auto.i18n.x_________d793c18b') || '日本語インターフェース', short: '日' }
  ];

  /* ---- key = 中文原文（简中） ---- */
  var DICT = (function () {
    var K = function (rows) { var o = {}; for (var i = 0; i < rows.length; i++) o[rows[i][0]] = rows[i][1]; return o; };
    return K([
      /* ---- 页眉 / 全局 ---- */
      [_t('auto.i18n.__mtscos_ai__f443ceb2') || _t('auto.i18n.__mtscos_ai__f443ceb2') || ' MTSCOS AI 就绪', {'zh-CN':' MTSCOS AI 就绪','zh-TW':_t('auto.i18n.__mtscos_ai__47819de8') || ' MTSCOS AI 就緒','en-US':' MTSCOS AI Ready','ja-JP':_t('auto.i18n.__mtscos_ai__754d8fea') || ' MTSCOS AI 準備完了'}],
      [_t('auto.i18n.x_56f5106c') || _t('auto.i18n.x_56f5106c') || '切换明暗主题', {'zh-CN':'切换明暗主题','zh-TW':_t('auto.i18n.x_ffdc4c4b') || '切換明暗主題','en-US':'Toggle Theme','ja-JP':_t('auto.i18n._______x_1616c469') || 'ライト/ダーク切替'}],
      [_t('auto.i18n.x___language_c4888b4a') || _t('auto.i18n.x___language_c4888b4a') || _t('auto.i18n.x___language_c4888b4a') || _t('auto.i18n.x___language_c4888b4a') || _t('auto.i18n.x___language_c4888b4a') || _t('auto.i18n.x___language_c4888b4a') || _t('auto.i18n.x___language_c4888b4a') || '切换语言 / Language', {'zh-CN':'切换语言 / Language','zh-TW':_t('auto.i18n.x___language_d3f6bb32') || '切換語言 / Language','en-US':'Switch Language','ja-JP':_t('auto.i18n.x_d5553cff') || _t('auto.i18n.x_d5553cff') || '言語切替'}],
      [_t('auto.i18n.x___x_locals_861ca4d4') || _t('auto.i18n.x___x_locals_861ca4d4') || _t('auto.i18n.x___x_locals_861ca4d4') || '请选择页面显示语言 · 偏好保存到 localStorage', {'zh-CN':'请选择页面显示语言 · 偏好保存到 localStorage','zh-TW':_t('auto.i18n.x___x_locals_f964ae9e') || '請選擇頁面顯示語言 · 偏好儲存到 localStorage','en-US':'Choose your display language · Preference saved to localStorage','ja-JP':_t('auto.i18n.x_x___x__loc_fba0c217') || '表示言語を選択 · 設定は localStorage に保存されます'}],
      [_t('auto.i18n.x_x_5fb65059') || _t('auto.i18n.x_x_5fb65059') || '当前：简体中文', {'zh-CN':'当前：简体中文','zh-TW':_t('auto.i18n.x_x_3d6463de') || '目前：簡体字中国語','en-US':_t('auto.i18n.current__x_bf8d6d73') || 'Current: 简体中文','ja-JP':_t('auto.i18n.x_x_3f47f4b9') || '現在：簡体字中国語'}],
      [_t('auto.i18n.x_x_ff36e276') || _t('auto.i18n.x_x_ff36e276') || '当前：繁體中文', {'zh-CN':'当前：繁體中文','zh-TW':_t('auto.i18n.x_x_24e3dfe2') || '目前：繁體中文','en-US':_t('auto.i18n.current__x_ae59fe6f') || 'Current: 繁體中文','ja-JP':_t('auto.i18n.x_x_515674be') || '現在：繁体字中国語'}],
      [_t('auto.i18n.x_english_a53b7375') || _t('auto.i18n.x_english_a53b7375') || '当前：English', {'zh-CN':'当前：English','zh-TW':_t('auto.i18n.x_english_ecc5c4d7') || '目前：English','en-US':'Current: English','ja-JP':_t('auto.i18n.x_english_a2b6b148') || '現在：English'}],
      [_t('auto.i18n.x_x_2214aff6') || _t('auto.i18n.x_x_2214aff6') || '当前：日本語', {'zh-CN':'当前：日本語','zh-TW':_t('auto.i18n.x_x_28430876') || '目前：日本語','en-US':_t('auto.i18n.current__x_d7c30530') || 'Current: 日本語','ja-JP':_t('auto.i18n.x_x_e332654b') || '現在：日本語'}],
      [_t('auto.i18n.x_769d88e4') || _t('auto.i18n.x_769d88e4') || _t('auto.i18n.x_769d88e4') || _t('auto.i18n.x_769d88e4') || '完成', {'zh-CN':'完成','zh-TW':'完成','en-US':'Done','ja-JP':_t('auto.i18n.x_6b2dfe06') || '完了'}],
      [_t('auto.i18n.x_b15d9127') || _t('auto.i18n.x_b15d9127') || _t('auto.i18n.x_b15d9127') || _t('auto.i18n.x_b15d9127') || '关闭', {'zh-CN':'关闭','zh-TW':_t('auto.i18n.x_b04c170b') || '關閉','en-US':'Close','ja-JP':_t('auto.i18n.x___5dce8628') || '閉じる'}],
      ['默认界面语言', {'zh-CN':'默认界面语言','zh-TW':_t('auto.i18n.x_f86bedaf') || '預設介面語言','en-US':'Default UI language','ja-JP':_t('auto.i18n._____uix_38b1110a') || 'デフォルトUI言語'}],
      [_t('auto.i18n.x_5056a470') || _t('auto.i18n.x_5056a470') || '繁體中文界面', {'zh-CN':'繁體中文界面','zh-TW':'繁體中文介面','en-US':'Traditional Chinese UI','ja-JP':_t('auto.i18n.xui_d01be511') || '繁体字中国語UI'}],
      ['English (US)', {'zh-CN':'English (US)','zh-TW':'English (US)','en-US':'English (US)','ja-JP':'English (US)'}],
      ['日本語インターフェース', {'zh-CN':_t('auto.i18n.x_b3c4dd7f') || '日语界面','zh-TW':_t('auto.i18n.x_0ac6561f') || '日語介面','en-US':'Japanese UI','ja-JP':'日本語インターフェース'}],
      [_t('auto.i18n.x__844513e2') || _t('auto.i18n.x__844513e2') || _t('auto.i18n.x__844513e2') || '界面语言已切换为：', {'zh-CN':'界面语言已切换为：','zh-TW':_t('auto.i18n.x__87d02e09') || '介面語言已切換為：','en-US':'Interface language switched to: ','ja-JP':_t('auto.i18n.uix_x_x______aae25943') || 'UI言語を切り替えました：'}],
      ['简体中文', {'zh-CN':'简体中文','zh-TW':_t('auto.i18n.x_ee151acb') || _t('auto.i18n.x_ee151acb') || '簡体字中国語','en-US':'Simplified Chinese','ja-JP':'簡体字中国語'}],
      ['繁體中文', {'zh-CN':_t('auto.i18n.x_dd16f5f4') || '繁体中文','zh-TW':'繁體中文','en-US':'Traditional Chinese','ja-JP':_t('auto.i18n.x_52ff07ef') || '繁体字中国語'}],
      [_t('auto.i18n.x_358a3ba1') || _t('auto.i18n.x_358a3ba1') || _t('auto.i18n.x_358a3ba1') || _t('auto.i18n.x_358a3ba1') || '语言切换', {'zh-CN':'语言切换','zh-TW':_t('auto.i18n.x_704b4d3f') || '語言切替','en-US':'Language','ja-JP':'言語切替'}],

      /* ---- 登录与设置（通用） ---- */
      [_t('auto.i18n.x_02314486') || _t('auto.i18n.x_02314486') || _t('auto.i18n.x_02314486') || '登录与注册', {'zh-CN':'登录与注册','zh-TW':_t('auto.i18n.x_90033ca6') || '登入與註冊','en-US':'Sign in / Register','ja-JP':_t('auto.i18n._______x_a2e00ce9') || _t('auto.i18n._______x_a2e00ce9') || 'ログイン / 会員登録'}],
      [_t('auto.i18n.x_aa8383f6') || _t('auto.i18n.x_aa8383f6') || _t('auto.i18n.x_aa8383f6') || '欢迎回来', {'zh-CN':'欢迎回来','zh-TW':_t('auto.i18n.x_2479fbd3') || '歡迎回來','en-US':'Welcome back','ja-JP':'おかえりなさい'}],
      ['MTSCOS AI', {'zh-CN':'MTSCOS AI','zh-TW':'MTSCOS AI','en-US':'MTSCOS AI','ja-JP':'MTSCOS AI'}],
      [_t('auto.i18n.x_819767ad') || _t('auto.i18n.x_819767ad') || _t('auto.i18n.x_819767ad') || '用户名', {'zh-CN':'用户名','zh-TW':_t('auto.i18n.x_ebd16edd') || '使用者名稱','en-US':'Username','ja-JP':_t('auto.i18n.____x_b9e8c768') || 'ユーザー名'}],
      [_t('auto.i18n.x_a8105204') || _t('auto.i18n.x_a8105204') || _t('auto.i18n.x_a8105204') || '密码', {'zh-CN':'密码','zh-TW':_t('auto.i18n.x_6662c848') || '密碼','en-US':'Password','ja-JP':'パスワード'}],
      [_t('auto.i18n.x_5f26be78') || _t('auto.i18n.x_5f26be78') || _t('auto.i18n.x_5f26be78') || '显示密码', {'zh-CN':'显示密码','zh-TW':_t('auto.i18n.x_57375deb') || '顯示密碼','en-US':'Show password','ja-JP':_t('auto.i18n._____x_db4ec1d5') || 'パスワード表示'}],
      [_t('auto.i18n.x_dd909adb') || _t('auto.i18n.x_dd909adb') || '隐藏密码', {'zh-CN':'隐藏密码','zh-TW':_t('auto.i18n.x_1c1bf8a8') || '隱藏密碼','en-US':'Hide password','ja-JP':_t('auto.i18n._____x_172dacb0') || 'パスワード非表示'}],
      [_t('auto.i18n.x_aef8e595') || _t('auto.i18n.x_aef8e595') || _t('auto.i18n.x_aef8e595') || '记住我', {'zh-CN':'记住我','zh-TW':_t('auto.i18n.x_83a880c5') || '記住我','en-US':'Remember me','ja-JP':_t('auto.i18n.____x_x_cefe8a40') || 'ログイン情報を保存'}],
      [_t('auto.i18n.x__8048909f') || _t('auto.i18n.x__8048909f') || _t('auto.i18n.x__8048909f') || '忘记密码？', {'zh-CN':'忘记密码？','zh-TW':_t('auto.i18n.x__8c4b14a5') || '忘記密碼？','en-US':'Forgot password?','ja-JP':_t('auto.i18n._______x_____45fa4f22') || 'パスワードをお忘れですか？'}],
      [_t('auto.i18n.x_x_e43613ca') || _t('auto.i18n.x_x_e43613ca') || _t('auto.i18n.x_x_e43613ca') || '登 录', {'zh-CN':'登 录','zh-TW':_t('auto.i18n.x_x_b00dae92') || '登 入','en-US':'Sign In','ja-JP':'ログイン'}],
      [_t('auto.i18n.x_402d19e5') || _t('auto.i18n.x_402d19e5') || '登录', {'zh-CN':'登录','zh-TW':_t('auto.i18n.x_6e00cae3') || '登入','en-US':'Sign In','ja-JP':'ログイン'}],
      [_t('auto.i18n.x_x_x_x_x_17551a49') || _t('auto.i18n.x_x_x_x_x_17551a49') || _t('auto.i18n.x_x_x_x_x_17551a49') || '创 建 新 账 户', {'zh-CN':'创 建 新 账 户','zh-TW':_t('auto.i18n.x_x_x_x_x_8ae06785') || '創 建 新 帳 戶','en-US':'Create Account','ja-JP':_t('auto.i18n.x_eeb5c568') || '新規会員登録'}],
      [_t('auto.i18n.x_1857e702') || _t('auto.i18n.x_1857e702') || _t('auto.i18n.x_1857e702') || '系统版本', {'zh-CN':'系统版本','zh-TW':_t('auto.i18n.x_123a36ab') || '系統版本','en-US':'System Version','ja-JP':'システムバージョン'}],
      [_t('auto.i18n.x_0719aa2b') || _t('auto.i18n.x_0719aa2b') || '重置密码', {'zh-CN':'重置密码','zh-TW':_t('auto.i18n.x_efaf8c00') || '重設密碼','en-US':'Reset Password','ja-JP':'パスワードをリセット'}],
      [_t('auto.i18n.x_54666047') || _t('auto.i18n.x_54666047') || '注册账户', {'zh-CN':'注册账户','zh-TW':_t('auto.i18n.x_3a3523c9') || '註冊帳戶','en-US':'Register Account','ja-JP':_t('auto.i18n._____x_4e20ac1c') || 'アカウント新規登録'}],

      /* ---- 页脚 产品栏目 ---- */
      [_t('auto.i18n.x_a015434e') || _t('auto.i18n.x_a015434e') || _t('auto.i18n.x_a015434e') || '产品', {'zh-CN':'产品','zh-TW':_t('auto.i18n.x_290023b7') || '產品','en-US':'Products','ja-JP':'プロダクト'}],
      [_t('auto.i18n.x_e586debb') || _t('auto.i18n.x_e586debb') || '考试与题库系统', {'zh-CN':'考试与题库系统','zh-TW':_t('auto.i18n.x_4a0399a1') || '考試與題庫系統','en-US':'Exam & Question Bank','ja-JP':_t('auto.i18n.x_x_____180d4f36') || '試験・問題銀行システム'}],
      [_t('auto.i18n.ai_x_c6e1d2ba') || _t('auto.i18n.ai_x_c6e1d2ba') || 'AI 辅导老师', {'zh-CN':'AI 辅导老师','zh-TW':_t('auto.i18n.ai_x_66d3667a') || 'AI 輔導老師','en-US':'AI Tutor','ja-JP':_t('auto.i18n.ai_x_dd3e0764') || 'AI 家庭教師'}],
      [_t('auto.i18n.x_25aa7eb9') || _t('auto.i18n.x_25aa7eb9') || '学情诊断', {'zh-CN':'学情诊断','zh-TW':_t('auto.i18n.x_aa3e3aa1') || '學情診斷','en-US':'Learning Diagnosis','ja-JP':_t('auto.i18n.x_1911e6aa') || '学習診断'}],
      [_t('auto.i18n.aix_686473b0') || _t('auto.i18n.aix_686473b0') || 'AI知识脑库', {'zh-CN':'AI知识脑库','zh-TW':_t('auto.i18n.aix_8202e904') || 'AI知識腦庫','en-US':'AI Knowledge Brain','ja-JP':'AI ナレッジベース'}],

      /* ---- 页脚 资源中心 ---- */
      [_t('auto.i18n.x_270c4e56') || _t('auto.i18n.x_270c4e56') || _t('auto.i18n.x_270c4e56') || '资源中心', {'zh-CN':'资源中心','zh-TW':_t('auto.i18n.x_3cd3649d') || '資源中心','en-US':'Resources','ja-JP':'リソースセンター'}],
      [_t('auto.i18n.x__1__5_x__2b696be7') || _t('auto.i18n.x__1__5_x__2b696be7') || '系统规范（§1-§5 硬约束）', {'zh-CN':'系统规范（§1-§5 硬约束）','zh-TW':_t('auto.i18n.x__1__5_x__0949d215') || '系統規範（§1-§5 硬約束）','en-US':'System Specs (§1–§5 Hard Constraints)','ja-JP':_t('auto.i18n.____x__1__5__9505807b') || 'システム規範（§1–§5 ハード制約）'}],
      [_t('auto.i18n.x__6_x__0d97862e') || _t('auto.i18n.x__6_x__0d97862e') || '使用文档（§6 快速开始）', {'zh-CN':'使用文档（§6 快速开始）','zh-TW':_t('auto.i18n.x__6_x__4bf07e89') || '使用文件（§6 快速開始）','en-US':'User Guide (§6 Quick Start)','ja-JP':'ユーザーガイド（§6 クイックスタート）'}],
      [_t('auto.i18n.__api_x__7_x_fb17cec7') || _t('auto.i18n.__api_x__7_x_fb17cec7') || ' API 接口（§7 对外能力）', {'zh-CN':' API 接口（§7 对外能力）','zh-TW':_t('auto.i18n.__api_x__7_x_c19199cb') || ' API 介面（§7 對外能力）','en-US':' API Reference (§7)','ja-JP':_t('auto.i18n.__api________6f4656ce') || ' API リファレンス（§7 外部機能）'}],
      [_t('auto.i18n.___x__8_x_x__5a0a8d63') || _t('auto.i18n.___x__8_x_x__5a0a8d63') || ' 系统规则（§8 安全/审计）', {'zh-CN':' 系统规则（§8 安全/审计）','zh-TW':_t('auto.i18n.___x__8_x_x__711553d6') || ' 系統規則（§8 安全/稽核）','en-US':' System Rules (§8 Security/Audit)','ja-JP':_t('auto.i18n._______x__8__43c9008a') || ' システム規則（§8 セキュリティ・監査）'}],
      [_t('auto.i18n.__x_faq__9__a3be2306') || _t('auto.i18n.__x_faq__9__a3be2306') || ' 常见问题 FAQ（§9）', {'zh-CN':' 常见问题 FAQ（§9）','zh-TW':_t('auto.i18n.__x_faq__9__f103c650') || ' 常見問題 FAQ（§9）','en-US':' FAQ (§9)','ja-JP':_t('auto.i18n.__faq__9_____0b44483f') || ' FAQ（§9 よくある質問）'}],

      /* ---- 页脚 快速入口 ---- */
      [_t('auto.i18n.x_c2eb151c') || _t('auto.i18n.x_c2eb151c') || _t('auto.i18n.x_c2eb151c') || _t('auto.i18n.x_c2eb151c') || '快速入口', {'zh-CN':'快速入口','zh-TW':'快速入口','en-US':'Quick Access','ja-JP':'クイックアクセス'}],
      [_t('auto.i18n.x___x_b86467e8') || _t('auto.i18n.x___x_b86467e8') || '登录 / 注册账户', {'zh-CN':'登录 / 注册账户','zh-TW':_t('auto.i18n.x___x_f5467186') || '登入 / 註冊帳戶','en-US':'Sign in / Register','ja-JP':'ログイン / 会員登録'}],
      [_t('auto.i18n.x___x_fa623c82') || _t('auto.i18n.x___x_fa623c82') || '考试中心 / 题库', {'zh-CN':'考试中心 / 题库','zh-TW':_t('auto.i18n.x___x_f28fc35b') || '考試中心 / 題庫','en-US':'Exam Center / Question Bank','ja-JP':_t('auto.i18n.x_______x_513999e6') || '試験センター / 問題銀行'}],
      [_t('auto.i18n.x_f5523d9c') || _t('auto.i18n.x_f5523d9c') || '教师工作台', {'zh-CN':'教师工作台','zh-TW':_t('auto.i18n.x_3bba4f31') || '教師工作台','en-US':'Teacher Console','ja-JP':_t('auto.i18n.x______dc59d2b0') || '教師コンソール'}],
      [_t('auto.i18n.x_ac6a5471') || _t('auto.i18n.x_ac6a5471') || '学生学习门户', {'zh-CN':'学生学习门户','zh-TW':_t('auto.i18n.x_6f525e42') || '學生學習入口網站','en-US':'Student Portal','ja-JP':_t('auto.i18n.x_____9c752c01') || '学生ポータル'}],
      [_t('auto.i18n.x___x_d3962e6c') || _t('auto.i18n.x___x_d3962e6c') || '个人设置 / 数据', {'zh-CN':'个人设置 / 数据','zh-TW':_t('auto.i18n.x___x_982c4d40') || '個人設定 / 數據','en-US':'Profile & Data','ja-JP':'プロフィールとデータ'}],
      [_t('auto.i18n.___mts_x_v2__4f504c49') || _t('auto.i18n.___mts_x_v2__4f504c49') || ' MTS 架构 v2.0', {'zh-CN':' MTS 架构 v2.0','zh-TW':_t('auto.i18n.___mts_x_v2__39067047') || ' MTS 架構 v2.0','en-US':' MTS Architecture v2.0','ja-JP':' MTS アーキテクチャ v2.0'}],

      /* ---- 联系我们 ---- */
      [_t('auto.i18n.x_0cbf83cc') || _t('auto.i18n.x_0cbf83cc') || _t('auto.i18n.x_0cbf83cc') || '联系我们', {'zh-CN':'联系我们','zh-TW':_t('auto.i18n.x_8b2327b1') || '聯絡我們','en-US':'Contact Us','ja-JP':_t('auto.i18n._x_x___e3daadda') || 'お問い合わせ'}],
      [_t('auto.i18n.x_96539652') || _t('auto.i18n.x_96539652') || '北京市海淀区科技园区', {'zh-CN':'北京市海淀区科技园区','zh-TW':_t('auto.i18n.x_cd666c7b') || '北京市海淀區科技園區','en-US':'Haidian Science Park, Beijing','ja-JP':_t('auto.i18n.x________b7459097') || '北京市海淀区ハイテクパーク'}],
      [_t('auto.i18n.x_9_00_18_00_10d8a179') || _t('auto.i18n.x_9_00_18_00_10d8a179') || '周一至周五 9:00-18:00', {'zh-CN':'周一至周五 9:00-18:00','zh-TW':_t('auto.i18n.x_9_00_18_00_fbbd86db') || '週一至週五 9:00-18:00','en-US':'Mon–Fri 9:00–18:00','ja-JP':_t('auto.i18n.x_x_9_00_18__1187edda') || '月〜金 9:00–18:00'}],
      [_t('auto.i18n.x_250752c5') || _t('auto.i18n.x_250752c5') || _t('auto.i18n.x_250752c5') || '社交媒体链接', {'zh-CN':'社交媒体链接','zh-TW':_t('auto.i18n.x_93716abb') || '社群媒體連結','en-US':'Follow Us','ja-JP':_t('auto.i18n.x______8ffb6b9b') || '公式アカウント'}],
      [_t('auto.i18n.github_x__x__329ac034') || _t('auto.i18n.github_x__x__329ac034') || 'GitHub 开源项目主页 (新窗口打开)', {'zh-CN':'GitHub 开源项目主页 (新窗口打开)','zh-TW':_t('auto.i18n.github_x__x__2c0c9152') || 'GitHub 開源專案首頁 (開新視窗)','en-US':'GitHub Project (opens new tab)','ja-JP':_t('auto.i18n.github_______a4d070e4') || 'GitHub プロジェクト（新規タブ）'}],
      [_t('auto.i18n.x_x_mtscos_a_2cb0c950') || _t('auto.i18n.x_x_mtscos_a_2cb0c950') || '微信公众号：扫码关注 MTSCOS AI', {'zh-CN':'微信公众号：扫码关注 MTSCOS AI','zh-TW':_t('auto.i18n.x_x_mtscos_a_bd865ade') || '微信公眾號：掃碼關注 MTSCOS AI','en-US':'WeChat: Scan to follow MTSCOS AI','ja-JP':_t('auto.i18n.wechat_x_____1d5faceb') || 'WeChat 公式：スキャンで MTSCOS AI をフォロー'}],
      [_t('auto.i18n.x__x__45c5067b') || _t('auto.i18n.x__x__45c5067b') || '官方微博 (新窗口打开)', {'zh-CN':'官方微博 (新窗口打开)','zh-TW':_t('auto.i18n.x__x__e40682b6') || '官方微博 (開新視窗)','en-US':'Official Weibo (opens new tab)','ja-JP':_t('auto.i18n.weibo_x_x____337f9b28') || 'Weibo 公式（新規タブ）'}],
      [_t('auto.i18n.x_rss_3f8ce146') || _t('auto.i18n.x_rss_3f8ce146') || '订阅系统更新与公告 RSS', {'zh-CN':'订阅系统更新与公告 RSS','zh-TW':_t('auto.i18n.x_rss_e85f337e') || '訂閱系統更新與公告 RSS','en-US':'Subscribe to updates (RSS)','ja-JP':_t('auto.i18n.x_x_rss__a369e1cc') || '更新情報を購読（RSS）'}],

      /* ---- 二维码模态 ---- */
      [_t('auto.i18n.x_8f467e91') || _t('auto.i18n.x_8f467e91') || '扫码关注', {'zh-CN':'扫码关注','zh-TW':_t('auto.i18n.x_fb9a0aa0') || '掃碼關注','en-US':'Scan to Follow','ja-JP':'スキャンしてフォロー'}],
      [_t('auto.i18n.x_d918f1ae') || _t('auto.i18n.x_d918f1ae') || '使用微信扫描下方二维码', {'zh-CN':'使用微信扫描下方二维码','zh-TW':_t('auto.i18n.x_af4e943f') || '使用微信掃描下方二維碼','en-US':'Scan the QR code below with WeChat','ja-JP':_t('auto.i18n.wechat__x_qr_072a3585') || 'WeChat で下のQRコードをスキャンしてください'}],
      [_t('auto.i18n.x_d0a1cf30') || _t('auto.i18n.x_d0a1cf30') || '使用微信扫一扫关注官方公众号', {'zh-CN':'使用微信扫一扫关注官方公众号','zh-TW':_t('auto.i18n.x_efc3b5c5') || '使用微信掃一掃關注官方公眾號','en-US':'Follow our Official Account via WeChat Scan','ja-JP':_t('auto.i18n.wechat_______dba704cc') || 'WeChat スキャンで公式アカウントをフォロー'}],
      [_t('auto.i18n.x_36c33f9c') || _t('auto.i18n.x_36c33f9c') || '扫码访问', {'zh-CN':'扫码访问','zh-TW':_t('auto.i18n.x_bc96a7db') || '掃碼訪問','en-US':'Scan to Visit','ja-JP':'スキャンでアクセス'}],

      /* ---- EigenFlux 面板 ---- */
      [_t('auto.i18n.eigenflux____e63aa903') || _t('auto.i18n.eigenflux____e63aa903') || 'EigenFlux · AI员工磋商结果（UI/粒子/页眉页脚事件）',
        {'zh-CN':'EigenFlux · AI员工磋商结果（UI/粒子/页眉页脚事件）','zh-TW':_t('auto.i18n.eigenflux____ec0e8c2f') || 'EigenFlux · AI員工磋商結果（UI/粒子/頁首頁尾事件）',
         'en-US':'EigenFlux · AI Staff Deliberation (UI / Particles / Header-Footer Events)',
         'ja-JP':_t('auto.i18n.eigenflux_ai_0c720622') || 'EigenFlux・AIスタッフ協議結果（UI / パーティクル / ヘッダー・フッター事象）'}],
      [_t('auto.i18n.__x_7c8e4881') || _t('auto.i18n.__x_7c8e4881') || ' 自动修复项', {'zh-CN':' 自动修复项','zh-TW':_t('auto.i18n.__x_85e5f440') || ' 自動修復項','en-US':' Auto-fixes Applied','ja-JP':_t('auto.i18n.__x_c245a881') || ' 自動修復項目'}],
      [_t('auto.i18n.__x_dd5a7fb7') || _t('auto.i18n.__x_dd5a7fb7') || ' 推荐动作', {'zh-CN':' 推荐动作','zh-TW':_t('auto.i18n.__x_8c46c879') || ' 推薦動作','en-US':' Recommended Actions','ja-JP':_t('auto.i18n.__x______c41c1381') || ' 推奨アクション'}],

      /* ---- 通用系统文案 ---- */
      [_t('auto.i18n.mtscos_ai____21bede4d') || _t('auto.i18n.mtscos_ai____21bede4d') || 'MTSCOS AI · MTS架构 驱动的智能学习评估平台',
        {'zh-CN':'MTSCOS AI · MTS架构 驱动的智能学习评估平台','zh-TW':_t('auto.i18n.mtscos_ai____894a9352') || 'MTSCOS AI · MTS架構 驅動的智能學習評估平台',
         'en-US':'MTSCOS AI · MTS Architecture Intelligent Learning Platform',
         'ja-JP':_t('auto.i18n.mtscos_ai_mt_b8bbdcb8') || 'MTSCOS AI・MTS アーキテクチャ駆動 知的学習評価プラットフォーム'}],
      [_t('auto.i18n.mtsx_5a0d293d') || _t('auto.i18n.mtsx_5a0d293d') || 'MTS架构', {'zh-CN':'MTS架构','zh-TW':_t('auto.i18n.mtsx_8af11f55') || 'MTS架構','en-US':'MTS Architecture','ja-JP':'MTS アーキテクチャ'}],
      [_t('auto.i18n.x____26b5bd49') || _t('auto.i18n.x____26b5bd49') || '加载中...', {'zh-CN':'加载中...','zh-TW':_t('auto.i18n.x____d3933730') || '載入中...','en-US':'Loading…','ja-JP':_t('auto.i18n.x_x_x__4699f535') || '読み込み中…'}],
      [_t('auto.i18n.x_c624290a') || _t('auto.i18n.x_c624290a') || '条记录', {'zh-CN':'条记录','zh-TW':_t('auto.i18n.x_86c63c75') || '筆記錄','en-US':'record(s)','ja-JP':_t('auto.i18n.x______5e7b08d0') || '件のレコード'}],
      [_t('auto.i18n.x_5a799607') || _t('auto.i18n.x_5a799607') || '版权所有', {'zh-CN':'版权所有','zh-TW':_t('auto.i18n.x_6dec8727') || '版權所有','en-US':'All Rights Reserved','ja-JP':_t('auto.i18n.x_90bbbe18') || '著作権所有'}],
      [_t('auto.i18n.x_b04ec75c') || _t('auto.i18n.x_b04ec75c') || '主页', {'zh-CN':'主页','zh-TW':_t('auto.i18n.x_469db73c') || _t('auto.i18n.x_469db73c') || '首頁','en-US':'Home','ja-JP':'ホーム'}],
      [_t('auto.i18n.x_db1c89e0') || _t('auto.i18n.x_db1c89e0') || '首页', {'zh-CN':'首页','zh-TW':'首頁','en-US':'Home','ja-JP':'ホーム'}],
      [_t('auto.i18n.x_5a136705') || _t('auto.i18n.x_5a136705') || '返回首页', {'zh-CN':'返回首页','zh-TW':_t('auto.i18n.x_a12e185b') || '返回首頁','en-US':'Back to Home','ja-JP':_t('auto.i18n.____x__7c55e296') || 'ホームに戻る'}],
      [_t('auto.i18n.x_e03183c0') || _t('auto.i18n.x_e03183c0') || '考试中心', {'zh-CN':'考试中心','zh-TW':_t('auto.i18n.x_365b2882') || '考試中心','en-US':'Exam Center','ja-JP':_t('auto.i18n.x_____c2b9550a') || '試験センター'}],
      [_t('auto.i18n.x_409120b5') || _t('auto.i18n.x_409120b5') || '个人中心', {'zh-CN':'个人中心','zh-TW':_t('auto.i18n.x_f2be7e3b') || '個人中心','en-US':'My Center','ja-JP':'マイページ'}],
      [_t('auto.i18n.x_b5c37706') || _t('auto.i18n.x_b5c37706') || _t('auto.i18n.x_b5c37706') || '控制台', {'zh-CN':'控制台','zh-TW':'控制台','en-US':'Dashboard','ja-JP':'ダッシュボード'}],
      [_t('auto.i18n.x_9aff6241') || _t('auto.i18n.x_9aff6241') || '监控', {'zh-CN':'监控','zh-TW':_t('auto.i18n.x_7e9b2ed7') || '監控','en-US':'Monitor','ja-JP':'モニター'}],
      [_t('auto.i18n.x_c8d7362a') || _t('auto.i18n.x_c8d7362a') || '权限不足', {'zh-CN':'权限不足','zh-TW':_t('auto.i18n.x_547c30f2') || '權限不足','en-US':'Permission Denied','ja-JP':_t('auto.i18n.x_______b7514369') || '権限がありません'}],
      [_t('auto.i18n.x_010c23b9') || _t('auto.i18n.x_010c23b9') || '页面未找到', {'zh-CN':'页面未找到','zh-TW':_t('auto.i18n.x_21dabac3') || '頁面未找到','en-US':'Page Not Found','ja-JP':_t('auto.i18n.____x_______fe75b4ed') || _t('auto.i18n.____x_______fe75b4ed') || 'ページが見つかりません'}],
      [_t('auto.i18n.x_d824805c') || _t('auto.i18n.x_d824805c') || '服务器错误', {'zh-CN':'服务器错误','zh-TW':_t('auto.i18n.x_78e0fa28') || '伺服器錯誤','en-US':'Server Error','ja-JP':'サーバーエラー'}],
      [_t('auto.i18n.x_b47f9b12') || _t('auto.i18n.x_b47f9b12') || '系统升级中', {'zh-CN':'系统升级中','zh-TW':_t('auto.i18n.x_77d8f679') || '系統升級中','en-US':'System Upgrade','ja-JP':_t('auto.i18n.___________x_903fbe7b') || 'システムアップグレード中'}],
      [_t('auto.i18n.x_3a955e29') || _t('auto.i18n.x_3a955e29') || _t('auto.i18n.x_3a955e29') || '通知中心', {'zh-CN':'通知中心','zh-TW':'通知中心','en-US':'Notifications','ja-JP':_t('auto.i18n.x_____fa14634e') || '通知センター'}],
      [_t('auto.i18n.x_d3e6516a') || _t('auto.i18n.x_d3e6516a') || '主题自定义', {'zh-CN':'主题自定义','zh-TW':_t('auto.i18n.x_01e6659f') || '主題自定義','en-US':'Personalize Theme','ja-JP':'テーマカスタマイズ'}],
      [_t('auto.i18n.x_cec71d08') || _t('auto.i18n.x_cec71d08') || '系统升级中心', {'zh-CN':'系统升级中心','zh-TW':_t('auto.i18n.x_ee53b40c') || '系統升級中心','en-US':'System Upgrade Center','ja-JP':'システムアップグレードセンター'}],
      [_t('auto.i18n.x_26240168') || _t('auto.i18n.x_26240168') || '学习门户', {'zh-CN':'学习门户','zh-TW':_t('auto.i18n.x_9a495a86') || '學習入口網站','en-US':'Learning Portal','ja-JP':_t('auto.i18n.x_____2596a194') || _t('auto.i18n.x_____2596a194') || '学習ポータル'}],
      [_t('auto.i18n.x_83833b12') || _t('auto.i18n.x_83833b12') || '考试分析', {'zh-CN':'考试分析','zh-TW':_t('auto.i18n.x_dc0e2672') || '考試分析','en-US':'Exam Analysis','ja-JP':_t('auto.i18n.x_642f780e') || '試験分析'}],
      [_t('auto.i18n.x_7d94de1c') || _t('auto.i18n.x_7d94de1c') || '用户管理', {'zh-CN':'用户管理','zh-TW':_t('auto.i18n.x_36b03353') || '使用者管理','en-US':'User Management','ja-JP':_t('auto.i18n.____x_64f1d924') || 'ユーザー管理'}],
      [_t('auto.i18n.x_6450d843') || _t('auto.i18n.x_6450d843') || '数据分析', {'zh-CN':'数据分析','zh-TW':_t('auto.i18n.x_73d01a86') || '數據分析','en-US':'Data Analysis','ja-JP':_t('auto.i18n.___x_627a9503') || 'データ分析'}],
      [_t('auto.i18n.x_6e598bc7') || _t('auto.i18n.x_6e598bc7') || '课程管理', {'zh-CN':'课程管理','zh-TW':_t('auto.i18n.x_47f7beff') || '課程管理','en-US':'Course Management','ja-JP':_t('auto.i18n.___x_5b1d6b53') || 'コース管理'}],
      [_t('auto.i18n.x_86f67d0e') || _t('auto.i18n.x_86f67d0e') || '题库', {'zh-CN':'题库','zh-TW':_t('auto.i18n.x_57ae4808') || '題庫','en-US':'Question Bank','ja-JP':_t('auto.i18n.x_d893bb54') || '問題銀行'}],
      [_t('auto.i18n.x_116e0772') || _t('auto.i18n.x_116e0772') || '作业', {'zh-CN':'作业','zh-TW':_t('auto.i18n.x_55d4da46') || '作業','en-US':'Assignment','ja-JP':_t('auto.i18n.x_454a8c85') || '課題'}],
      [_t('auto.i18n.x_fa86f1a5') || _t('auto.i18n.x_fa86f1a5') || _t('auto.i18n.x_fa86f1a5') || '公告', {'zh-CN':'公告','zh-TW':'公告','en-US':'Announcements','ja-JP':_t('auto.i18n._x___4fa5ebfc') || 'お知らせ'}],
      [_t('auto.i18n.x_b347513e') || _t('auto.i18n.x_b347513e') || '教师仪表盘', {'zh-CN':'教师仪表盘','zh-TW':_t('auto.i18n.x_0533430f') || '教師儀表板','en-US':'Teacher Dashboard','ja-JP':_t('auto.i18n.x________d9f3fc58') || '教師ダッシュボード'}],
      [_t('auto.i18n.x_e366ccf1') || _t('auto.i18n.x_e366ccf1') || '设置', {'zh-CN':'设置','zh-TW':_t('auto.i18n.x_029c0df6') || _t('auto.i18n.x_029c0df6') || '設定','en-US':'Settings','ja-JP':'設定'}],
      [_t('auto.i18n.x_44efd179') || _t('auto.i18n.x_44efd179') || '退出登录', {'zh-CN':'退出登录','zh-TW':_t('auto.i18n.x_75c856b1') || '登出','en-US':'Sign Out','ja-JP':'ログアウト'}],

      /* ---- 品牌长文 (页脚) ---- */
      ['MTSCOS AI Intelligent Learning Platform',
        {'zh-CN':'MTSCOS AI Intelligent Learning Platform','zh-TW':'MTSCOS AI Intelligent Learning Platform',
         'en-US':'MTSCOS AI · Intelligent Learning Platform','ja-JP':_t('auto.i18n.mtscos_ai_x__1c04d057') || 'MTSCOS AI 知的学習プラットフォーム'}],
      [_t('auto.i18n.mtscos_ai____879a3955') || _t('auto.i18n.mtscos_ai____879a3955') || 'MTSCOS AI · MTS架构 驱动的智能学习评估平台，覆盖 K12 / 成人 / 高等教育 全场景。基于自主学习的AI脑库，提供自适应出题、智能诊断、学情画像、AI答疑等一体化能力。',
        {'zh-CN':'MTSCOS AI · MTS架构 驱动的智能学习评估平台，覆盖 K12 / 成人 / 高等教育 全场景。基于自主学习的AI脑库，提供自适应出题、智能诊断、学情画像、AI答疑等一体化能力。',
         'zh-TW':_t('auto.i18n.mtscos_ai____7e4ec664') || 'MTSCOS AI · MTS架構 驅動的智能學習評估平台，覆蓋 K12 / 成人 / 高等教育 全場景。基於自主學習的AI腦庫，提供自適應出題、智能診斷、學情畫像、AI答疑等一體化能力。',
         'en-US':'MTSCOS AI · MTS Architecture powered Intelligent Learning Platform. Full-scope coverage for K12 / Adult / Higher education. Built on an autonomous AI brain library to deliver unified capabilities: adaptive question generation, intelligent diagnosis, learner profiling, and AI Q&A.',
         'ja-JP':_t('auto.i18n.mtscos_ai_mt_9c9414da') || 'MTSCOS AI・MTS アーキテクチャ駆動の知的学習評価プラットフォーム。K12 / 社会人 / 高等教育 の全シナリオをカバー。自律学習型 AI ブレインライブラリを基盤に、適応的な出題・知的診断・学習者プロファイル・AI Q&A などの統合機能を提供します。'}],

      /* ---- 异常页家族 (40x/50x) · 短 key ---- */
      [_t('auto.i18n.x_dcb3648d') || _t('auto.i18n.x_dcb3648d') || '您没有权限访问此页面', {'zh-CN':'您没有权限访问此页面','zh-TW':_t('auto.i18n.x_d2229d0a') || '您沒有權限訪問此頁面','en-US':'You do not have permission to access this page.','ja-JP':_t('auto.i18n._____________7afad1b3') || 'このページにアクセスする権限がありません。'}],
      [_t('auto.i18n.x_61e2ea60') || _t('auto.i18n.x_61e2ea60') || '需要登录后才能继续操作', {'zh-CN':'需要登录后才能继续操作','zh-TW':_t('auto.i18n.x_df9eb915') || '需要登入後才能繼續操作','en-US':'Please sign in to continue.','ja-JP':_t('auto.i18n.x____________ac71bd80') || '続行するにはログインしてください。'}],
      [_t('auto.i18n.x_fa15b15a') || _t('auto.i18n.x_fa15b15a') || '页面不存在或已被删除', {'zh-CN':'页面不存在或已被删除','zh-TW':_t('auto.i18n.x_94acb0bf') || '頁面不存在或已被刪除','en-US':'This page does not exist or has been removed.','ja-JP':_t('auto.i18n.____x_____x__1c529430') || 'ページが存在しないか、削除されました。'}],
      [_t('auto.i18n.x_x_dd390e07') || _t('auto.i18n.x_x_dd390e07') || '服务器临时不可用，请稍后重试', {'zh-CN':'服务器临时不可用，请稍后重试','zh-TW':_t('auto.i18n.x_x_69c203ef') || '伺服器暫時不可用，請稍後重試','en-US':'Server is temporarily unavailable. Please try again later.','ja-JP':_t('auto.i18n._____x_x_____d0e1807e') || 'サーバーは一時的に利用できません。しばらくしてから再試行してください。'}],
      [_t('auto.i18n.x_4f980084') || _t('auto.i18n.x_4f980084') || '网关错误', {'zh-CN':'网关错误','zh-TW':_t('auto.i18n.x_20d9d622') || '閘道錯誤','en-US':'Bad Gateway','ja-JP':'ゲートウェイエラー'}],
      [_t('auto.i18n.x_bdf53f26') || _t('auto.i18n.x_bdf53f26') || '请求超时', {'zh-CN':'请求超时','zh-TW':_t('auto.i18n.x_a8150920') || '請求逾時','en-US':'Request Timeout','ja-JP':'リクエストタイムアウト'}],
      [_t('auto.i18n.x_904329d7') || _t('auto.i18n.x_904329d7') || '请求格式错误', {'zh-CN':'请求格式错误','zh-TW':_t('auto.i18n.x_2db6f8d6') || '請求格式錯誤','en-US':'Bad Request','ja-JP':_t('auto.i18n.x_______81db16f4') || '不正なリクエスト'}],
      [_t('auto.i18n.x_x_e7ece142') || _t('auto.i18n.x_x_e7ece142') || '系统维护中，预计很快恢复', {'zh-CN':'系统维护中，预计很快恢复','zh-TW':_t('auto.i18n.x_x_a7baa11d') || '系統維護中，預計很快恢復','en-US':'Under maintenance. Back soon.','ja-JP':_t('auto.i18n.______x______bed5be3e') || 'メンテナンス中です。まもなく復旧します。'}],
      [_t('auto.i18n.x_x_2f90fbd9') || _t('auto.i18n.x_x_2f90fbd9') || '速率限制：操作过于频繁', {'zh-CN':'速率限制：操作过于频繁','zh-TW':_t('auto.i18n.x_x_58f6c05f') || '速率限制：操作過於頻繁','en-US':'Rate limit exceeded: too many requests','ja-JP':_t('auto.i18n.___x_______x_04767e4d') || 'レート制限：リクエストが多すぎます'}],

      /* ---- 403 异常页（系统容器拦截） ---- */
      [_t('auto.i18n.__x_d0b994e0') || _t('auto.i18n.__x_d0b994e0') || ' 访问被系统容器拦截', {'zh-CN':' 访问被系统容器拦截','zh-TW':_t('auto.i18n.__x_401195ee') || ' 存取被系統容器攔截','en-US':' Blocked by System Container','ja-JP':' システムコンテナによりアクセスがブロックされました'}],
      [_t('auto.i18n.x_da271987') || _t('auto.i18n.x_da271987') || '访问被系统容器拦截', {'zh-CN':'访问被系统容器拦截','zh-TW':_t('auto.i18n.x_7afb01eb') || '存取被系統容器攔截','en-US':'Blocked by System Container','ja-JP':'システムコンテナによりアクセスがブロックされました'}],
      [_t('auto.i18n.__x_bfa6f584') || _t('auto.i18n.__x_bfa6f584') || '<- 返回首页', {'zh-CN':'<- 返回首页','zh-TW':_t('auto.i18n.__x_3505d78b') || '<- 回到首頁','en-US':'<- Back to Home','ja-JP':_t('auto.i18n.______x__4dd4d20b') || '<- ホームに戻る'}],
      [_t('auto.i18n.x_afa4b723') || _t('auto.i18n.x_afa4b723') || '需要管理员权限', {'zh-CN':'需要管理员权限','zh-TW':_t('auto.i18n.x_b7c46013') || '需要管理員權限','en-US':'Admin privileges required','ja-JP':_t('auto.i18n.x_x___b04d6331') || '管理者権限が必要です'}],
      [_t('auto.i18n.2_x_7555231c') || _t('auto.i18n.2_x_7555231c') || '2 秒后自动返回首页', {'zh-CN':'2 秒后自动返回首页','zh-TW':_t('auto.i18n.2_x_b3da567b') || '2 秒後自動回到首頁','en-US':'Auto redirecting to Home in 2 seconds','ja-JP':_t('auto.i18n.2_x_x_____x__09a714f1') || '2 秒後に自動的にホームへ戻ります'}],

      /* ---- 404 异常页 ---- */
      [_t('auto.i18n.404_x_5079f653') || _t('auto.i18n.404_x_5079f653') || '404 页面不存在', {'zh-CN':'404 页面不存在','zh-TW':_t('auto.i18n.404_x_6f54307d') || '404 頁面不存在','en-US':'404 Page Not Found','ja-JP':_t('auto.i18n.404_____x____939ef8e4') || '404 ページが見つかりません'}],
      [_t('auto.i18n.x_509d3dfb') || _t('auto.i18n.x_509d3dfb') || '页面不存在', {'zh-CN':'页面不存在','zh-TW':_t('auto.i18n.x_60b76a0a') || '頁面不存在','en-US':'Page Not Found','ja-JP':'ページが見つかりません'}],
      [_t('auto.i18n.x_d788506b') || _t('auto.i18n.x_d788506b') || '您可能想访问', {'zh-CN':'您可能想访问','zh-TW':_t('auto.i18n.x_5a908fd5') || '您可能想造訪','en-US':'You may want to visit','ja-JP':_t('auto.i18n._____x_____861554e6') || 'こちらもご覧ください'}],
      [_t('auto.i18n.x_1b002886') || _t('auto.i18n.x_1b002886') || '未找到路径', {'zh-CN':'未找到路径','zh-TW':_t('auto.i18n.x_1e4ec1ff') || '未找到路徑','en-US':'Path not found','ja-JP':_t('auto.i18n.___x_______15fdb911') || 'パスが見つかりません'}],
      [_t('auto.i18n.x_5c526fa5') || _t('auto.i18n.x_5c526fa5') || '系统入口', {'zh-CN':'系统入口','zh-TW':_t('auto.i18n.x_49c5ceca') || '系統入口','en-US':'System Entry','ja-JP':_t('auto.i18n.____x_dbd357f9') || 'システム入口'}],
      [_t('auto.i18n.x_0830693a') || _t('auto.i18n.x_0830693a') || '学习入口', {'zh-CN':'学习入口','zh-TW':_t('auto.i18n.x_145a7e84') || '學習入口','en-US':'Learning Portal','ja-JP':'学習ポータル'}],
      [_t('auto.i18n.x_8bab32d9') || _t('auto.i18n.x_8bab32d9') || '考试与练习', {'zh-CN':'考试与练习','zh-TW':_t('auto.i18n.x_387a63dd') || '考試與練習','en-US':'Exams & Practice','ja-JP':_t('auto.i18n.x_x_aaa33850') || '試験・演習'}],
      [_t('auto.i18n.x_27e0ca87') || _t('auto.i18n.x_27e0ca87') || '返回上一页', {'zh-CN':'返回上一页','zh-TW':_t('auto.i18n.x_67961877') || '返回上一頁','en-US':'Go Back','ja-JP':_t('auto.i18n.x_____x__d4864f58') || '前のページに戻る'}]
    ]);
  })();

  var KEY_ALIASES = {
    loginRegister:'登录与注册', welcomeBack:'欢迎回来', username:'用户名',
    password:'密码', showPwd:'显示密码', rememberMe:'记住我',
    forgotPwd:'忘记密码？', signIn:'登 录', createAccount:'创 建 新 账 户',
    sysVersion:'系统版本', products:'产品', resources:'资源中心',
    quickAccess:'快速入口', contactUs:'联系我们', followUs:'社交媒体链接',
    done:'完成', close:'关闭', switchLang:'切换语言 / Language',
    langTitle:'语言切换'
  };

  var STORAGE_KEY = 'mtscos_ui_language';
  var SNAPSHOT_ATTR = 'data-i18n-orig';
  var FAB_ID = 'mtscos-i18n-fab';
  var MODAL_ID = 'lang-modal';

  /* ================= 工具函数 ================= */
  function _normWs(s) {
    return String(s || '').replace(/[\u00A0\u3000\u2002-\u200B\t\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
  }
  function detectBrowserLang() {
    if (!navigator || !navigator.language) return 'zh-CN';
    var raw = (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language;
    var low = String(raw).toLowerCase();
    if (low.indexOf('zh-tw') === 0 || low.indexOf('zh-hk') === 0) return 'zh-TW';
    if (low.indexOf('zh') === 0) return 'zh-CN';
    if (low.indexOf('ja') === 0) return 'ja-JP';
    if (low.indexOf('en') === 0) return 'en-US';
    return 'zh-CN';
  }
  function currentLang() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return saved;
      var detected = detectBrowserLang();
      try { localStorage.setItem(STORAGE_KEY, detected); } catch (_) {}
      return detected;
    } catch (_) { return detectBrowserLang(); }
  }

  /* ================= 原文快照 ================= */
  var _snapshotted = false;
  function snapshotRootTexts(root) {
    if (_snapshotted) return;
    try {
      var walker = document.createTreeWalker(
        root || document.body,
        NodeFilter.SHOW_TEXT,
        { acceptNode: function (n) {
            if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
            var v = n.nodeValue.trim();
            if (!v) return NodeFilter.FILTER_REJECT;
            if (v.length > 320) return NodeFilter.FILTER_REJECT;
            var p = n.parentNode;
            if (!p) return NodeFilter.FILTER_REJECT;
            var nn = p.nodeName;
            if (nn === 'STYLE' || nn === 'SCRIPT' || nn === 'NOSCRIPT' || nn === 'TEMPLATE' ||
                nn === 'CODE' || nn === 'PRE' || nn === 'TEXTAREA' || nn === 'IFRAME') {
              return NodeFilter.FILTER_REJECT;
            }
            return NodeFilter.FILTER_ACCEPT;
        }}
      );
      var list = []; var n;
      while ((n = walker.nextNode())) list.push(n);
      for (var i = 0; i < list.length; i++) {
        var nd = list[i]; var p = nd.parentNode;
        if (!p.getAttribute(SNAPSHOT_ATTR)) {
          var txt = (p.textContent || '').trim().slice(0, 320);
          if (txt) p.setAttribute(SNAPSHOT_ATTR, txt);
        }
      }
      _snapshotted = true;
    } catch (_) { /* ignore */ }
  }

  /* ================= 元素翻译 ================= */
  function _longestDirectText(el) {
    var b = '', bl = 0;
    for (var c = el.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) {
        var t = (c.nodeValue || '');
        if (t.length > bl) { b = t; bl = t.length; }
      }
    }
    return b;
  }

  var _normDict = null;
  function _lookupRow(key) {
    if (!key) return null;
    if (DICT[key]) return DICT[key];
    /* 空白归一后匹配 */
    if (!_normDict) {
      _normDict = {};
      var all = Object.keys(DICT);
      for (var i = 0; i < all.length; i++) _normDict[_normWs(all[i])] = DICT[all[i]];
    }
    var nk = _normWs(key);
    if (_normDict[nk]) return _normDict[nk];
    /* 最后：前缀回退（长 key 或 短 key） */
    var keys = Object.keys(DICT);
    for (var k = 0; k < keys.length; k++) {
      if (keys[k] === key || keys[k].indexOf(key) === 0 || key.indexOf(keys[k]) === 0) return DICT[keys[k]];
    }
    return null;
  }

  function translateElement(el, code) {
    if (!el || !el.getAttribute) return;
    var key = el.getAttribute('data-i18n');
    if (key && KEY_ALIASES[key]) key = KEY_ALIASES[key];
    if (!key) {
      var orig = el.getAttribute(SNAPSHOT_ATTR);
      if (orig) key = orig;
      else {
        if (el.childElementCount === 0) key = (el.textContent || '').trim().slice(0, 320);
        else {
          var lt = _longestDirectText(el);
          key = lt ? lt.trim().slice(0, 320) : '';
        }
      }
    }
    var row = _lookupRow(key);
    if (!row) return;
    var val = row[code] != null ? row[code] : row['zh-CN'];
    if (val == null || val === '') return;

    if (el.nodeName === 'INPUT' || el.nodeName === 'TEXTAREA' || el.nodeName === 'SELECT') {
      /* 保护用户值：仅在 value 为空或与默认 placeholder 相同时不覆盖；此处不改 value，
         只处理 placeholder / title / aria-label */
      var ph = el.getAttribute('placeholder');
      if (ph && DICT[ph]) el.setAttribute('placeholder', DICT[ph][code] || ph);
    } else {
      var title = el.getAttribute('title');
      if (title && DICT[title]) el.setAttribute('title', (DICT[title][code]) || title);
      var arial = el.getAttribute('aria-label');
      if (arial && DICT[arial]) el.setAttribute('aria-label', (DICT[arial][code]) || arial);

      /* 判断是否全是纯文本子节点 */
      var onlyText = true, hasText = false, subCount = 0;
      for (var c = el.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 1 /* ELEMENT */) onlyText = false;
        if (c.nodeType === 3) { hasText = true; }
        subCount++;
      }
      if (hasText && onlyText) {
        el.textContent = val;
      } else if (hasText) {
        /* 替换最长 TEXT_NODE */
        var best = null, bl = 0;
        for (var cc = el.firstChild; cc; cc = cc.nextSibling) {
          if (cc.nodeType === 3) {
            var t = (cc.nodeValue || '');
            if (t.length > bl) { best = cc; bl = t.length; }
          }
        }
        if (best) best.nodeValue = ' ' + val + ' ';
        else if (el.childElementCount === 0) el.textContent = val;
      }
    }
  }

  function applyTranslations(code) {
    snapshotRootTexts(document.body);

    /* 模态相关文本 */
    var titleEl = document.getElementById('lang-modal-title');
    if (titleEl) translateElement(titleEl, code);
    var tips = document.querySelectorAll('.mtscos-modal-desc, .mtscos-modal-tip');
    for (var i = 0; i < tips.length; i++) translateElement(tips[i], code);

    /* 带标记的节点 */
    var tagged = document.querySelectorAll('[data-i18n], [' + SNAPSHOT_ATTR + ']');
    for (var j = 0; j < tagged.length; j++) translateElement(tagged[j], code);

    /* 常见标签兜底（含带图标按钮） */
    var TAGS = ['A','BUTTON','SPAN','LABEL','H1','H2','H3','H4','H5','H6','P','SMALL','STRONG','LI','TD','TH','DIV','SUMMARY','LEGEND','CAPTION'];
    for (var t = 0; t < TAGS.length; t++) {
      var nodes = document.getElementsByTagName(TAGS[t]);
      for (var n = 0; n < nodes.length; n++) {
        var el = nodes[n];
        if (!el || !el.getAttribute) continue;
        if (el.getAttribute('data-i18n-done') === '1') continue;
        var orig = el.getAttribute(SNAPSHOT_ATTR);
        var txtRaw = orig || (el.childElementCount === 0 ? (el.textContent || '') : _longestDirectText(el));
        var txt = String(txtRaw || '').trim().slice(0, 320);
        if (!txt) continue;
        if (DICT[txt] || _lookupRow(txt)) translateElement(el, code);
      }
    }

    /* 选项卡当前语言 label 翻译 */
    try {
      var tip = document.getElementById('lang-modal-tip');
      if (tip) {
        var info = (LANGS.find(function (l) { return l.code === code; }) || LANGS[0]);
        var localKey = _t('auto.i18n.x__3d490bfc') || _t('auto.i18n.x__3d490bfc') || '当前：' + info.label;
        if (DICT[localKey]) tip.textContent = DICT[localKey][code] || localKey;
        else tip.textContent = localKey;
      }
    } catch (_) {}

    /* 页面标题 */
    if (code === 'en-US') document.title = 'MTSCOS AI · MTS Architecture | Intelligent Learning Platform';
    else if (code === 'ja-JP') document.title = _t('auto.i18n.mtscos_ai____d3a4e328') || 'MTSCOS AI · MTSアーキテクチャ | 知的学習評価プラットフォーム';
    else if (code === 'zh-TW') document.title = _t('auto.i18n.mtscos_ai____49ab2c61') || 'MTSCOS AI · MTS架構 | 智能學習評估平台';
  }

  /* ================= 语言应用 ================= */
  function _labelShort(info) {
    return info.short || (info.code.indexOf('zh') === 0 ? '中' : (info.code.indexOf('en') === 0 ? 'EN' : info.code.substring(0, 2)));
  }
  function applyLang(code) {
    var info = LANGS.find(function (l) { return l.code === code; }) || LANGS[0];
    try { document.documentElement.setAttribute('lang', info.code); } catch(_){}
    try { document.body.setAttribute('data-ui-lang', info.code); } catch(_){}
    try { localStorage.setItem(STORAGE_KEY, info.code); } catch (_) {}

    /* 更新页眉按钮 label 或 FAB label */
    var hl = document.getElementById('header-lang-label');
    if (!hl) {
      var fab = document.getElementById(FAB_ID);
      if (fab) hl = fab.querySelector('.i18n-fab__label') || fab;
    }
    if (hl) hl.textContent = _labelShort(info);

    /* 更新 lunar 文本 */
    try {
      var lunarEl = document.querySelector('.header-lunar-calendar');
      if (lunarEl) {
        var zhT = lunarEl.getAttribute('data-lunar-zh') || '';
        var enT = lunarEl.getAttribute('data-lunar-en') || '';
        var textEl = lunarEl.querySelector('.lunar-text');
        if (textEl) textEl.textContent = (info.code.indexOf('en') === 0 && enT) ? enT : zhT;
      }
    } catch (_) {}

    try { applyTranslations(info.code); } catch (e) {
      try { console.warn('[mtscos-i18n] applyTranslations failed:', (e && e.message) || e); } catch (_) {}
    }

    /* 渲染模态内部选项 */
    try { renderOptions(); } catch (_) {}

    /* 轻量 toast：若页面已有 showToast 则使用，否则原生 console */
    try {
      var prefixKey = '界面语言已切换为：';
      var prefix = (DICT[prefixKey] && DICT[prefixKey][info.code]) ? DICT[prefixKey][info.code] :
                   (info.code.indexOf('zh') === 0 ? prefixKey : 'Interface language switched to: ');
      var labelText = (DICT[info.label] && DICT[info.label][info.code]) ? DICT[info.label][info.code] : info.label;
      if (typeof window.showToast === 'function') window.showToast(prefix + labelText);
      else try { console.log('[mtscos-i18n] ' + prefix + labelText); } catch (_) {}
    } catch (_) {}
  }

  /* ================= 模态 UI 渲染 ================= */
  function renderOptions() {
    var wrap = document.getElementById('lang-options');
    if (!wrap) return;
    var cur = currentLang();
    wrap.innerHTML = '';
    LANGS.forEach(function (l) {
      var active = l.code === cur;
      var d = document.createElement('button');
      d.type = 'button';
      d.className = 'lang-option' + (active ? ' is-active' : '');
      d.setAttribute('role', 'option');
      d.setAttribute('aria-selected', active ? 'true' : 'false');
      d.setAttribute('data-lang-code', l.code);
      d.innerHTML =
        '<span class="lang-flag">' + l.flag + '</span>' +
        '<span class="lang-body">' +
          '<span class="lang-label">' + l.label + '</span>' +
          '<small class="lang-tip">' + l.tip + '</small>' +
        '</span>' +
        (active ? '<i class="fas fa-circle-check lang-check" aria-hidden="true"></i>' : '');
      d.addEventListener('click', function () {
        applyLang(l.code);
        renderOptions();
      });
      wrap.appendChild(d);
    });
  }

  /* ================= 模态打开 / 关闭 ================= */
  function toggleLangModal() {
    var modal = document.getElementById(MODAL_ID);
    if (!modal) return;
    var isOpen = modal.getAttribute('aria-hidden') === 'false' || modal.classList.contains('is-open');
    if (isOpen) closeLangModal();
    else {
      modal.setAttribute('aria-hidden', 'false');
      modal.classList.add('is-open');
      modal.style.display = 'flex';
      try { document.body.style.overflow = 'hidden'; } catch (_) {}
      renderOptions();
      try { applyTranslations(currentLang()); } catch (_) {}
    }
  }
  function closeLangModal() {
    var modal = document.getElementById(MODAL_ID);
    if (!modal) return;
    modal.setAttribute('aria-hidden', 'true');
    modal.classList.remove('is-open');
    modal.style.display = 'none';
    try { document.body.style.overflow = ''; } catch (_) {}
  }

  /* ================= 自动装配 UI：按钮 & 模态 ================= */
  function _hasAnyHeaderLangButton() {
    return !!(document.querySelector('#header-lang-btn, .header-lang, [data-role="lang-switcher"], [onclick*="__toggleLangModal"]'));
  }
  function _findHeaderActionsAnchor() {
    var sels = ['.header-actions', 'nav .el-menu--horizontal', '.top-bar', '.header > *:last-child', '.navbar-actions', '.app-header .right'];
    for (var i = 0; i < sels.length; i++) {
      var n = document.querySelector(sels[i]);
      if (n) return n;
    }
    return null;
  }

  function ensureLangModalDOM() {
    if (document.getElementById(MODAL_ID)) return;
    var info = LANGS.find(function (l) { return l.code === currentLang(); }) || LANGS[0];
    var titleKey = KEY_ALIASES.langTitle ? KEY_ALIASES.langTitle : '语言切换';
    var curTip = '当前：' + info.label;
    var descKey = '请选择页面显示语言 · 偏好保存到 localStorage';
    var html =
      '<div class="mtscos-modal" id="' + MODAL_ID + '" role="dialog" aria-modal="true" aria-labelledby="lang-modal-title" aria-hidden="true">' +
        '<div class="mtscos-modal-inner" role="document">' +
          '<div class="mtscos-modal-header">' +
            '<h3 class="mtscos-modal-title" id="lang-modal-title" data-i18n="langTitle"><i class="fas fa-language" aria-hidden="true"></i>' + titleKey + '</h3>' +
            '<button type="button" class="mtscos-modal-close" aria-label="' + (typeof window.t === 'function' ? _t('auto.i18n.x_b15d9127') : '关闭') + '" onclick="window.__closeLangModal && window.__closeLangModal()">' +
              '<i class="fas fa-xmark" aria-hidden="true"></i>' +
            '</button>' +
          '</div>' +
          '<p class="mtscos-modal-desc">' + descKey + '</p>' +
          '<div id="lang-options" role="listbox" aria-label="language list"></div>' +
          '<div class="mtscos-modal-footer">' +
            '<span class="mtscos-modal-tip" id="lang-modal-tip">' + curTip + '</span>' +
            '<button type="button" class="mtscos-modal-btn" id="lang-modal-done" onclick="window.__closeLangModal && window.__closeLangModal()">完成</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    var holder = document.body || document.documentElement;
    if (holder && holder.insertAdjacentHTML) holder.insertAdjacentHTML('beforeend', html);
  }

  function ensureHeaderLangButton() {
    if (_hasAnyHeaderLangButton()) return;
    var cur = currentLang();
    var info = LANGS.find(function (l) { return l.code === cur; }) || LANGS[0];
    var label = _labelShort(info);
    var anchor = _findHeaderActionsAnchor();
    if (anchor) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'header-lang-btn';
      btn.className = 'header-lang';
      btn.setAttribute('data-role', 'lang-switcher');
      btn.setAttribute('title', '切换语言 / Language');
      btn.setAttribute('aria-label', '切换语言 / Language');
      btn.innerHTML = '<i class="fas fa-language" aria-hidden="true"></i><span id="header-lang-label">' + label + '</span>';
      btn.addEventListener('click', toggleLangModal);
      try { anchor.appendChild(btn); } catch (_) { _injectFab(label); }
    } else {
      _injectFab(label);
    }
  }

  function _injectFab(label) {
    if (document.getElementById(FAB_ID)) return;
    var fab = document.createElement('button');
    fab.type = 'button';
    fab.id = FAB_ID;
    fab.className = 'i18n-fab';
    fab.setAttribute('title', '切换语言 / Language');
    fab.setAttribute('aria-label', '切换语言 / Language');
    fab.innerHTML = '<i class="fas fa-language" aria-hidden="true"></i><span id="header-lang-label" class="i18n-fab__label">' + label + '</span>';
    fab.addEventListener('click', toggleLangModal);
    try { (document.body || document.documentElement).appendChild(fab); } catch (_) {}
  }

  function ensureLangUIOnce() {
    try {
      ensureLangModalDOM();
      ensureHeaderLangButton();
    } catch (e) {
      try { console.warn('[mtscos-i18n] ensureLangUIOnce error:', (e && e.message) || e); } catch (_) {}
    }
  }

  /* ================= 全局事件绑定 ================= */
  function _bindGlobalOnce() {
    if (window.__MTSCOS_I18N_BOUND__) return;
    window.__MTSCOS_I18N_BOUND__ = true;
    try {
      document.addEventListener('keydown', function (e) {
        if (e && e.key === 'Escape') closeLangModal();
      });
      document.addEventListener('click', function (e) {
        var modal = document.getElementById(MODAL_ID);
        if (!modal) return;
        if (e.target === modal) closeLangModal();
      });
    } catch (_) {}
  }

  /* ================= 对外统一接口 ================= */
  window.__toggleLangModal = toggleLangModal;
  window.__closeLangModal = closeLangModal;
  window.__mtscos_i18n = {
    get: function (key, code) {
      var real = KEY_ALIASES[key] ? KEY_ALIASES[key] : key;
      var row = _lookupRow(real); if (!row) return key;
      return row[code || currentLang()] != null ? row[code || currentLang()] : row['zh-CN'];
    },
    setLang: applyLang,
    getLang: currentLang,
    langs: LANGS.slice(),
    apply: function () { applyTranslations(currentLang()); },
    ensureUI: ensureLangUIOnce,
    dict: DICT
  };

  /* ================= 启动 ================= */
  function _bootstrap() {
    /* 1) 先装配 UI 容器 */
    ensureLangUIOnce();
    /* 2) 绑定全局 */
    _bindGlobalOnce();
    /* 3) 快照原文 + 应用当前语言 (此时 LANGS/DICT 用 fallback 字面量) */
    try { applyLang(currentLang()); } catch (e) {
      try { console.warn('[mtscos-i18n] bootstrap applyLang error:', (e && e.message) || e); } catch (_) {}
    }
    /* 4)  仙女座 AI 修复: fetch 后端完整字典 -> 构建 window.t -> 重翻译 */
    try {
      fetch('/api/i18n/dict').then(function(r) { return r.json(); }).then(function(data) {
        if (data && data.dict && Object.keys(data.dict).length > 0) {
          var _dict = data.dict;
          // 构建 window.t(key, default) — 全项目通用!
          window.t = function(key, def) {
            if (!key) return def || '';
            // 先查后端字典 (hash key 如 auto.i18n.x_46c49965)
            if (_dict[key]) return _dict[key];
            // 再查前端 DICT 翻译
            var row = DICT[key];
            if (row && typeof row === 'object' && row[data.lang]) return row[data.lang];
            return def || key;
          };
          console.log('[mtscos-i18n]  window.t 已构建, dict=' + Object.keys(_dict).length + ' 条, lang=' + data.lang);
          // 重翻译 (现在 window.t 有了, LANGS/DICT 是初始化时的 fallback)
          applyLang(currentLang());
        }
      }).catch(function(e) {
        console.warn('[mtscos-i18n] fetch /api/i18n/dict 失败, 用 fallback', (e && e.message) || e);
      });
    } catch (e) { /* fetch 不支持, 忽略 */ }
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(_bootstrap, 0);
  } else {
    document.addEventListener('DOMContentLoaded', _bootstrap);
    /* 双重保险（DOMContentLoaded 早于此脚本时，setTimeout 兜底） */
    setTimeout(_bootstrap, 60);
  }
})();
