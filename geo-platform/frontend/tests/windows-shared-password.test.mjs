import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const gate = readFileSync(new URL("../src/AccessGate.tsx", import.meta.url), "utf8");

test("共享密码与旧邀请凭证使用各自的服务端字段", () => {
  assert.match(gate, /session\?\.mode === "INVITATION" \? "access_key" : "password"/);
  assert.match(gate, /登录密码/);
  assert.match(gate, /访问凭证/);
  assert.doesNotMatch(gate, /name="password"/);
});

test("共享密码登录界面不暴露预算或模型配置", () => {
  assert.doesNotMatch(gate, /Token|人民币|单价|预算/);
});
