"use strict";

const { spawnSync } = require("node:child_process");

/**
 * 使用跨平台 Node 参数启动 Next.js，统一处理内存上限和生产构建环境变量。
 *
 * @param {string} requestedCommand - package.json 传入的 Next.js 子命令。
 * @returns {number} 子进程退出码；参数无效或进程无法启动时返回非零值。
 *
 * 该入口避免在 Windows shell 中使用 POSIX 风格的 `KEY=value command` 写法；
 * 生产构建只在当前子进程设置 APP_ENV，不修改调用方的全局环境。
 */
function runNextCommand(requestedCommand) {
  const isProductionBuild = requestedCommand === "build:prod";
  const nextCommand = isProductionBuild ? "build" : requestedCommand;
  const allowedCommands = new Set(["start", "dev", "build", "export"]);

  if (!allowedCommands.has(nextCommand)) {
    console.error(`不支持的 Next.js 命令：${requestedCommand}`);
    return 2;
  }

  const memoryLimit = nextCommand === "dev" ? "16384" : "8192";
  const environment = { ...process.env };
  // 企业离线构建不发送框架遥测，也避免写入 Windows 用户级遥测配置。
  environment.NEXT_TELEMETRY_DISABLED = "1";
  if (isProductionBuild) {
    environment.APP_ENV = "prod";
  }

  const nextCli = require.resolve("next/dist/bin/next");
  const result = spawnSync(
    process.execPath,
    [`--max-old-space-size=${memoryLimit}`, nextCli, nextCommand],
    { env: environment, stdio: "inherit" },
  );

  if (result.error) {
    console.error(`启动 Next.js 失败：${result.error.message}`);
    return 1;
  }
  return result.status ?? 1;
}

/** 从命令行读取 package.json 传入的子命令并设置退出码。 */
function main() {
  const requestedCommand = process.argv[2] ?? "";
  process.exitCode = runNextCommand(requestedCommand);
}

main();
