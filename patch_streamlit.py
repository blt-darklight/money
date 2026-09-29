# -*- coding: utf-8 -*-
"""给 Streamlit 前端打兼容补丁（老内核手机浏览器专用）。

解决的问题（旧手机浏览器不支持新 JS API，页面报英文错误）：
1. "ReferenceError: structuredClone is not defined"
   —— 展开「查看明细数据」等表格组件时崩溃（st.dataframe 依赖）
2. "Bad message format" + "Object.keys(...).toSorted is not a function"
   —— 页面加载时弹黑色报错框（Streamlit 主题处理依赖 toSorted）
3. 手机浏览器「强制深色模式」把页面颜色反白反黑
   —— 声明 color-scheme = only light，告知浏览器本页面只有浅色版，
      关闭算法性暗化（Chromium 系内核：Chrome/Edge/大多数国产浏览器）

原理：往 streamlit 安装目录的前端 index.html <head> 顶部注入 polyfill
脚本与 meta 声明。streamlit 重装/升级后补丁会被覆盖，所以 start.bat 每次
启动前都会重跑本脚本（幂等：已打过则跳过，不会重复注入）。

手动执行：python patch_streamlit.py
"""
import os

import streamlit

MARK = "<!-- pnl-compat-patch v1 -->"

POLYFILL = """
if (typeof window.structuredClone !== "function") {
  window.structuredClone = function (value) {
    function cl(v, seen) {
      if (v === null || typeof v !== "object") return v;
      if (v instanceof Date) return new Date(v.getTime());
      if (v instanceof RegExp) return new RegExp(v.source, v.flags);
      if (v instanceof Map) {
        var m = new Map(); seen.set(v, m);
        v.forEach(function (val, k) { m.set(cl(k, seen), cl(val, seen)); });
        return m;
      }
      if (v instanceof Set) {
        var s = new Set(); seen.set(v, s);
        v.forEach(function (val) { s.add(cl(val, seen)); });
        return s;
      }
      if (ArrayBuffer.isView(v)) {
        return new v.constructor(v.buffer ? v.buffer.slice(0) : v);
      }
      var out = Array.isArray(v) ? [] : {};
      seen.set(v, out);
      Object.keys(v).forEach(function (k) { out[k] = cl(v[k], seen); });
      return out;
    }
    return cl(value, new WeakMap());
  };
}
if (!Array.prototype.toSorted) {
  Object.defineProperty(Array.prototype, "toSorted", {
    value: function (cmp) { return Array.from(this).sort(cmp); },
    writable: true, configurable: true
  });
}
if (!Object.hasOwn) {
  Object.defineProperty(Object, "hasOwn", {
    value: function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); },
    writable: true, configurable: true
  });
}
if (!String.prototype.replaceAll) {
  Object.defineProperty(String.prototype, "replaceAll", {
    value: function (a, b) {
      return a instanceof RegExp
        ? this.replace(a.flags.indexOf("g") >= 0 ? a : new RegExp(a.source, a.flags + "g"), b)
        : this.split(a).join(b);
    },
    writable: true, configurable: true
  });
}
"""

INJECT = (
    MARK
    + '\n    <meta name="color-scheme" content="only light" />'
    + "\n    <script>" + POLYFILL + "</script>"
)


def main() -> None:
    idx = os.path.join(os.path.dirname(streamlit.__file__),
                       "static", "index.html")
    with open(idx, encoding="utf-8") as f:
        html = f.read()
    if MARK in html:
        print("[OK] streamlit 前端补丁已存在，跳过。")
        return
    anchor = '<meta charset="UTF-8" />'
    if anchor not in html:
        raise SystemExit(f"[X] 未找到注入点（{anchor!r}），index.html 结构可能已变化：{idx}")
    html = html.replace(anchor, anchor + "\n    " + INJECT, 1)
    with open(idx, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 已注入兼容补丁：{idx}")


if __name__ == "__main__":
    main()
