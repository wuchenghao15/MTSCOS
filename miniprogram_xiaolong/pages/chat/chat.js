const api = require('../../utils/api');
const app = getApp();

Page({
  data: {
    logged: false,
    username: '',
    password: '',
    sessionId: '',
    messages: [],
    draft: '',
    sending: false,
    status: '连接中…',
    server: api.BASE,
  },

  onLoad() {
    this.checkLogin();
  },

  checkLogin() {
    const token = wx.getStorageSync('xl_token');
    if (!token) { this.setData({ logged: false, status: '未登录' }); return; }
    api.bootstrap(wx.getStorageSync('xl_device_id'))
      .then((j) => {
        this.setData({ logged: true, status: '已连接 · ' + (j.user ? j.user.username : '') });
        api.heartbeat(wx.getStorageSync('xl_device_id')).catch(() => {});
      })
      .catch((e) => {
        this.setData({ logged: false, status: e.code === 'scope_locked' ? '需网页端申请开通' : '未登录' });
      });
  },

  onUserInput(e) { this.setData({ username: e.detail.value }); },
  onPassInput(e) { this.setData({ password: e.detail.value }); },
  onDraft(e) { this.setData({ draft: e.detail.value }); },

  doLogin() {
    const { username, password } = this.data;
    if (!username || !password) { wx.showToast({ title: '请填写账号密码', icon: 'none' }); return; }
    wx.showLoading({ title: '登录中' });
    api.login(username, password)
      .then((j) => {
        wx.hideLoading();
        if (!j.success) { wx.showToast({ title: j.message || '登录失败', icon: 'none' }); return; }
        this.setData({ logged: true, password: '', status: '已连接 · ' + j.user.username });
      })
      .catch((e) => { wx.hideLoading(); wx.showToast({ title: e.message || '登录失败', icon: 'none' }); });
  },

  doRegister() {
    const { username, password } = this.data;
    if (!username || !password) { wx.showToast({ title: '请填写账号密码', icon: 'none' }); return; }
    wx.showLoading({ title: '注册中' });
    api.register(username, password)
      .then((j) => {
        wx.hideLoading();
        if (!j.success) { wx.showToast({ title: j.message || '注册失败', icon: 'none' }); return; }
        wx.showModal({
          title: '注册成功',
          content: '小龙端注册的账号仅开放聊天功能。如需使用其他功能，请到网页端冰山首页登录本账号申请开通。',
          showCancel: false,
        });
        this.setData({ logged: true, password: '', status: '已连接 · ' + j.user.username });
      })
      .catch((e) => { wx.hideLoading(); wx.showToast({ title: e.message || '注册失败', icon: 'none' }); });
  },

  send() {
    const text = (this.data.draft || '').trim();
    if (!text || this.data.sending) return;
    const msgs = this.data.messages.concat([{ role: 'user', text }]);
    const idx = msgs.length;
    msgs.push({ role: 'assistant', text: '' });
    this.setData({ messages: msgs, draft: '', sending: true });

    api.sendStream(
      { session_id: this.data.sessionId, message: text, model: 'qwen2.5-coder:14b', page_context: '小龙小程序' },
      (tok) => {
        const list = this.data.messages;
        list[idx].text += tok;
        this.setData({ messages: list });
      },
      () => this.setData({ sending: false }),
      (err) => {
        const list = this.data.messages;
        list[idx].text = list[idx].text || ('出错了: ' + err);
        this.setData({ messages: list, sending: false });
      }
    );
  },

  newSession() {
    this.setData({ sessionId: '', messages: [] });
  },

  openApply() {
    wx.setClipboardData({
      data: 'http://100.106.220.96:8888/xiaolong/apply',
      success: () => wx.showToast({ title: '申请地址已复制', icon: 'none' }),
    });
  },
});
