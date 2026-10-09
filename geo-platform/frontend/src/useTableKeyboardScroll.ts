import { useEffect } from "react";

// Ant's scroll container is outside the customizable table body.
export function useTableKeyboardScroll() {
  useEffect(() => {
    const root = document.querySelector(".app-shell");
    if (!root) return;
    const observed = new Set<HTMLElement>();
    let frame = 0;
    const refresh = () => {
      frame = 0;
      for (const node of observed) {
        if (!node.isConnected) { resize.unobserve(node); observed.delete(node); }
      }
      root.querySelectorAll<HTMLElement>(".ant-table-content, .ant-table-body").forEach(node => {
        if (!observed.has(node)) { observed.add(node); resize.observe(node); }
        if (node.scrollWidth > node.clientWidth || node.scrollHeight > node.clientHeight) {
          node.tabIndex = 0;
          node.setAttribute("role", "region");
          const titles = Array.from(node.querySelectorAll("thead th")).map(th => th.textContent?.trim()).filter(Boolean);
          node.setAttribute("aria-label", titles.length ? `表格：${titles.join("、")}` : "表格内容");
        } else {
          node.removeAttribute("tabindex");
          node.removeAttribute("role");
          node.removeAttribute("aria-label");
        }
      });
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(refresh); };
    const resize = new ResizeObserver(schedule);
    const mutations = new MutationObserver(schedule);
    mutations.observe(root, { childList: true, subtree: true, characterData: true });
    schedule();
    return () => { cancelAnimationFrame(frame); mutations.disconnect(); resize.disconnect(); };
  }, []);
}
