import test from "node:test";
import assert from "node:assert/strict";

import { canSeeNavItem } from "./visibility.ts";
import { navigation } from "./navigation.ts";

const viewerSnapshot = {
  source: "live",
  isSystemAdmin: false,
  permissions: ["monitoring.read", "lead.read"],
  globalPermissions: [],
  leadAccess: "allowed",
};

test("public pages are visible to every live user", () => {
  assert.equal(canSeeNavItem({ id: "overview", scope: "public" }, viewerSnapshot), true);
});

test("project pages require the matching read capability", () => {
  assert.equal(
    canSeeNavItem({ id: "monitoring", scope: "project", permissions: ["monitoring.read"] }, viewerSnapshot),
    true,
  );
  assert.equal(
    canSeeNavItem({ id: "questions", scope: "project", permissions: ["question.read"] }, viewerSnapshot),
    false,
  );
});

test("any-of gating supports internal diagnostics", () => {
  const diagnostics = {
    id: "diagnostics",
    scope: "project",
    permissions: ["monitoring.execute", "project.member.manage"],
    match: "any",
  };
  assert.equal(
    canSeeNavItem(diagnostics, { ...viewerSnapshot, permissions: ["project.member.manage"] }),
    true,
  );
  assert.equal(
    canSeeNavItem(diagnostics, { ...viewerSnapshot, permissions: ["monitoring.read"] }),
    false,
  );
});

test("global pages use permissions from any project", () => {
  const engines = { id: "engines", scope: "global", permissions: ["engine.verify"] };
  assert.equal(
    canSeeNavItem(engines, { ...viewerSnapshot, globalPermissions: [] }),
    false,
  );
  assert.equal(
    canSeeNavItem(engines, {
      ...viewerSnapshot,
      permissions: ["monitoring.read"],
      globalPermissions: ["engine.verify"],
    }),
    true,
  );
  assert.equal(
    canSeeNavItem(engines, { ...viewerSnapshot, isSystemAdmin: true, globalPermissions: [] }),
    true,
  );
});

test("system pages only show for system administrators", () => {
  assert.equal(canSeeNavItem({ id: "members", scope: "system" }, viewerSnapshot), false);
  assert.equal(
    canSeeNavItem({ id: "members", scope: "system" }, { ...viewerSnapshot, isSystemAdmin: true }),
    true,
  );
});

test("leads are hidden when the backend denies lead access", () => {
  const leads = { id: "leads", scope: "project", permissions: ["lead.read"] };
  assert.equal(canSeeNavItem(leads, { ...viewerSnapshot, leadAccess: "forbidden" }), false);
  assert.equal(canSeeNavItem(leads, viewerSnapshot), true);
});

test("loading state only exposes public pages", () => {
  assert.equal(canSeeNavItem({ id: "overview", scope: "public" }, undefined), true);
  assert.equal(
    canSeeNavItem({ id: "monitoring", scope: "project", permissions: ["monitoring.read"] }, undefined),
    false,
  );
});

test("mock mode keeps all pages visible for UI development", () => {
  assert.equal(
    canSeeNavItem(
      { id: "engines", scope: "global", permissions: ["engine.verify"] },
      { source: "mock" },
    ),
    true,
  );
});

const projectRead = [
  "project.read",
  "question.read",
  "monitoring.read",
  "evidence.read",
  "content.read",
  "publish.read",
  "channel.read",
  "lead.read",
  "stats.read",
];

const roleSnapshots = {
  sys_admin: { isSystemAdmin: true, permissions: [], globalPermissions: [] },
  project_admin: {
    permissions: [
      ...projectRead,
      "content.review",
      "evidence.review",
      "channel.write",
      "competitor.write",
      "brand.manage",
      "metric.manage",
      "engine.verify",
      "export.data",
      "audit.read",
      "project.member.manage",
      "budget.read",
      "budget.write",
      "budget.approve",
    ],
    globalPermissions: ["engine.verify"],
  },
  editor: {
    permissions: [
      "project.read",
      "question.read",
      "question.write",
      "monitoring.read",
      "monitoring.execute",
      "evidence.read",
      "content.read",
      "content.write",
      "publish.read",
      "publish.execute",
      "channel.read",
      "channel.write",
      "competitor.write",
      "brand.manage",
      "metric.manage",
      "engine.verify",
      "stats.read",
      "export.data",
      "budget.read",
      "budget.write",
    ],
    globalPermissions: ["engine.verify"],
  },
  reviewer: {
    permissions: [
      "project.read",
      "question.read",
      "monitoring.read",
      "evidence.read",
      "evidence.review",
      "content.read",
      "content.review",
      "stats.read",
      "audit.read",
      "budget.read",
      "budget.approve",
    ],
    globalPermissions: [],
  },
  viewer: {
    permissions: [...projectRead, "export.data"],
    globalPermissions: [],
  },
  lead_ops: {
    permissions: ["project.read", "lead.read", "lead.write"],
    globalPermissions: [],
  },
};

const expectedVisible = {
  sys_admin: ["overview", "projects", "engines"],
  project_admin: navigation.map((item) => item.id),
  editor: ["overview", "projects", "monitoring", "competitors", "brand", "diagnostics", "questions", "samples", "plans", "publishing", "channels", "quotes", "budget", "statistics", "metrics", "reviews", "faq", "materials", "engines"],
  reviewer: ["overview", "projects", "monitoring", "competitors", "brand", "questions", "samples", "plans", "quotes", "budget", "statistics", "metrics", "reviews", "faq", "materials", "activity"],
  viewer: ["overview", "projects", "monitoring", "competitors", "brand", "questions", "samples", "plans", "publishing", "channels", "quotes", "statistics", "metrics", "reviews", "leads", "faq", "materials"],
  lead_ops: ["overview", "projects", "leads"],
};

const visibleIds = (role) => navigation
  .filter((item) => canSeeNavItem(item, {
    source: "live",
    leadAccess: "allowed",
    ...roleSnapshots[role],
  }))
  .map((item) => item.id);

for (const role of Object.keys(roleSnapshots)) {
  test(`role matrix: ${role}`, () => {
    assert.deepEqual(visibleIds(role), expectedVisible[role]);
  });
}
