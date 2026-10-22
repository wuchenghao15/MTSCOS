// 小龙 · 仙女座聊天小程序
// 服务器统一指向 mini (小龙 = mini), 外部入口一律走 Tailscale 100.106.220.96
const API_BASE = 'http://100.106.220.96:8888';
const API_FALLBACK = 'https://mtos.site';

App({
  globalData: {
    apiBase: API_BASE,
    apiFallback: API_FALLBACK,
    token: '',
    user: null,
    deviceId: '',
  },
  onLaunch() {
    this.globalData.token = wx.getStorageSync('xl_token') || '';
    let d = wx.getStorageSync('xl_device_id');
    if (!d) {
      d = 'wx-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      wx.setStorageSync('xl_device_id', d);
    }
    this.globalData.deviceId = d;
  },
});
