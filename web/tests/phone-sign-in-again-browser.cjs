/** Focused local reauthentication journey. The intercepted response replaces the sensitive action; no code, text or call is sent. */
const { chromium } = require("playwright");
const { randomUUID } = require("node:crypto");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const base = process.env.RAFII_WEB_URL || "http://localhost:3293";
if (!["localhost", "127.0.0.1"].includes(new URL(base).hostname))
  throw new Error("Local fake harness only");

const id = randomUUID();
const headers = {
  Authorization: `Bearer dev:${id}`,
  "Content-Type": "application/json",
  "X-PostRiff-Request": "founder-alpha",
};
const tourIds = [
  ...fs
    .readFileSync(path.resolve(__dirname, "../src/features/onboarding/tours.ts"), "utf8")
    .matchAll(/^ {2,4}id: '([a-z-]+)'/gm),
].map((match) => match[1]);
const tours = JSON.stringify({
  completed: {},
  dismissed: Object.fromEntries(tourIds.map((name) => [name, 1])),
  nudged: {},
});

(async () => {
  const verified = await fetch(base + "/api/auth/verify", {
    method: "POST",
    headers,
    body: JSON.stringify({ plan: "studio" }),
  });
  assert.ok(
    verified.ok,
    `POST /api/auth/verify: ${verified.status} ${await verified.clone().text()}`,
  );
  const { workspaceId } = await verified.json();
  assert.ok(workspaceId);

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.addCookies([
      { name: "postriff_dev", value: "1", url: base },
      { name: "postriff_dev_principal", value: id, url: base },
      { name: "postriff_theme", value: "rafii", url: base },
    ]);
    await context.addInitScript(
      ({ principal, tours }) => {
        localStorage.setItem("postriff-dev-principal", principal);
        localStorage.setItem("postriff-onboarding", tours);
      },
      { principal: id, tours },
    );
    const page = await context.newPage();
    let logoutRequests = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname === "/api/auth/logout")
        logoutRequests++;
    });
    await page.goto(base + "/app/account/notifications", {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });
    const section = page.locator("#phone-mode");
    await section.getByText("No phone number saved.", { exact: true }).waitFor({ timeout: 90000 });
    await section.getByText("Call Rafii by phone", { exact: true }).click();
    await page.route(`**/api/workspaces/${workspaceId}/phone/inbound-codes`, (route) =>
      route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({
          error: "Sign in again to confirm this sensitive action.",
          code: "step_up_required",
        }),
      }),
    );
    await section.getByRole("button", { name: "Create phone sign-in code", exact: true }).click();

    const alert = section
      .getByRole("alert")
      .filter({ hasText: "to confirm this sensitive action." });
    const action = alert.getByRole("button", { name: "Sign in again", exact: true });
    await action.waitFor();
    assert.match(
      await action.evaluate((element) => getComputedStyle(element).textDecorationLine),
      /underline/,
      "Fresh sign-in action looks like a link",
    );
    assert.ok(
      await action.evaluate((element) => element.getBoundingClientRect().height >= 16),
      "Fresh sign-in action remains directly clickable",
    );
    const linkScreenshot =
      process.env.RAFII_PHONE_REAUTH_LINK_EVIDENCE || "/tmp/rafii-phone-sign-in-again-link.png";
    await section.screenshot({ path: linkScreenshot });
    await action.click();

    await page.waitForURL((url) => url.pathname === "/auth/sign-in");
    await page.getByRole("heading", { name: "Sign in to Rafii", exact: true }).waitFor();
    const signInUrl = new URL(page.url());
    assert.equal(
      signInUrl.searchParams.get("next"),
      "/app/account/notifications",
      "Fresh sign-in returns to the page that requested it",
    );
    assert.equal(logoutRequests, 1, "Fresh sign-in performs one explicit logout");
    assert.equal(
      await page.evaluate(() => localStorage.getItem("postriff-dev-principal")),
      null,
      "Fresh sign-in clears the local identity",
    );
    assert.equal(
      (await context.cookies()).some((cookie) => cookie.name === "postriff_dev"),
      false,
      "Fresh sign-in clears the session cookie",
    );
    const redirectScreenshot =
      process.env.RAFII_PHONE_REAUTH_EVIDENCE || "/tmp/rafii-phone-sign-in-again.png";
    await page.screenshot({ path: redirectScreenshot, fullPage: true });
    console.log(
      JSON.stringify({
        status: "PASS",
        execution: "actual local web UI + intercepted step-up response",
        checks: [
          "underlined clickable Sign in again action",
          "one explicit logout",
          "local identity cleared",
          "session cookie cleared",
          "sign-in redirect",
          "safe return path",
        ],
        realCalls: 0,
        screenshots: [linkScreenshot, redirectScreenshot],
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
