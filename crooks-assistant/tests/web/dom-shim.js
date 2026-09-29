/* A very small DOM stand-in for exercising web/ui.js under Node.
 *
 * It implements exactly what the renderer uses — createElement, textContent, appendChild,
 * className/classList, dataset, setAttribute, addEventListener — and records everything so a
 * test can assert what was built. It deliberately has no innerHTML: if the renderer ever
 * reached for it, the test run would throw.
 */
'use strict';

class ClassList {
  constructor(el) { this.el = el; }
  _set() { return new Set((this.el.className || '').split(/\s+/).filter(Boolean)); }
  _write(set) { this.el.className = [...set].join(' '); }
  add(...names) { const s = this._set(); names.forEach((n) => s.add(n)); this._write(s); }
  remove(...names) { const s = this._set(); names.forEach((n) => s.delete(n)); this._write(s); }
  contains(name) { return this._set().has(name); }
  // As the DOM's: with `force`, added when it is true and removed when it is false.
  toggle(name, force) {
    const s = this._set();
    const on = force === undefined ? !s.has(name) : !!force;
    if (on) s.add(name); else s.delete(name);
    this._write(s);
    return on;
  }
}

class Node {
  constructor(type) { this.nodeType = type; this.parentNode = null; }
}

class Text extends Node {
  constructor(data) { super(3); this.data = String(data); }
  get textContent() { return this.data; }
  allText() { return this.data; }
  toString() { return this.data; }
}

class Element extends Node {
  constructor(tag, ns) {
    super(1);
    this.tagName = String(tag).toUpperCase();
    this.namespaceURI = ns || null;
    this.childNodes = [];
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.className = '';
    this.hidden = false;
    this.classList = new ClassList(this);
    // Inline custom properties only: what the renderer sets (a number of its own making).
    const props = {};
    this.style = { setProperty: (k, v) => { props[k] = String(v); }, getPropertyValue: (k) => props[k] || '' };
  }
  appendChild(node) {
    if (!(node instanceof Node)) throw new TypeError('appendChild expects a Node');
    if (node.nodeType === 11) {
      // A fragment empties itself into its new parent, as in the real DOM.
      for (const child of node.childNodes.slice()) this.appendChild(child);
      node.childNodes = [];
      return node;
    }
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    this.childNodes.push(node);
    return node;
  }
  removeChild(node) { const i = this.childNodes.indexOf(node); if (i !== -1) this.childNodes.splice(i, 1); node.parentNode = null; return node; }
  replaceChild(fresh, old) {
    const i = this.childNodes.indexOf(old);
    if (i === -1) throw new Error('replaceChild: not a child');
    if (fresh.parentNode) fresh.parentNode.removeChild(fresh);
    this.childNodes[i] = fresh;
    fresh.parentNode = this;
    old.parentNode = null;
    return old;
  }
  insertBefore(node, before) {
    if (node.parentNode) node.parentNode.removeChild(node);
    const i = before ? this.childNodes.indexOf(before) : -1;
    if (i === -1) this.childNodes.push(node); else this.childNodes.splice(i, 0, node);
    node.parentNode = this;
    return node;
  }
  get firstChild() { return this.childNodes[0] || null; }
  // web/notify.js puts a control-local message directly AFTER its control, which is
  // `insertBefore(note, control.nextSibling)` — the ordinary DOM way, and a gap in this
  // stand-in until a test asked where the message had landed.
  get nextSibling() {
    if (!this.parentNode) return null;
    const kids = this.parentNode.childNodes;
    return kids[kids.indexOf(this) + 1] || null;
  }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(value) { this.childNodes = []; if (value !== '' && value !== null && value !== undefined) this.appendChild(new Text(value)); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type, detail) { for (const fn of this.listeners[type] || []) fn(Object.assign({ type, target: this, currentTarget: this, preventDefault() {} }, detail || {})); }
  setPointerCapture() {}
  releasePointerCapture() {}
  focus() { document.activeElement = this; }
  blur() { if (document.activeElement === this) document.activeElement = null; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  querySelectorAll(selector) {
    // Only what the tests need: ".class", "tag" and '[attr="value"]' selectors, descendants included.
    const out = [];
    const attr = /^\[([a-z-]+)="([^"]*)"\]$/.exec(selector);
    // A data-* attribute is read from `dataset` as well: the renderer writes those through
    // `el.dataset`, which the real DOM reflects into attributes and this shim does not.
    const attrValue = (el, name) => {
      const direct = el.getAttribute(name);
      if (direct !== null) return direct;
      if (!name.startsWith('data-')) return null;
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return Object.prototype.hasOwnProperty.call(el.dataset, key) ? String(el.dataset[key]) : null;
    };
    const match = (el) => (attr ? attrValue(el, attr[1]) === attr[2] : selector.startsWith('.') ? el.classList.contains(selector.slice(1)) : el.tagName === selector.toUpperCase());
    const walk = (el) => { for (const c of el.children) { if (match(c)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  get innerHTML() { throw new Error('innerHTML must not be used'); }
  set innerHTML(_) { throw new Error('innerHTML must not be used'); }
  get outerHTML() { throw new Error('outerHTML must not be used'); }
  insertAdjacentHTML() { throw new Error('insertAdjacentHTML must not be used'); }
  // Every string that reached the tree, in order, for assertions.
  allText() { return this.childNodes.map((n) => n.allText()).join(''); }
  countNodes() { return 1 + this.childNodes.reduce((n, c) => n + (c.nodeType === 1 ? c.countNodes() : 1), 0); }
}

class Fragment extends Element {
  constructor() { super('#document-fragment'); this.nodeType = 11; }
}

const document = {
  activeElement: null,
  createElement: (tag) => new Element(tag),
  createElementNS: (ns, tag) => new Element(tag, ns),
  createTextNode: (data) => new Text(data),
  createDocumentFragment: () => new Fragment(),
};

module.exports = { document, Element, Text, Fragment };
