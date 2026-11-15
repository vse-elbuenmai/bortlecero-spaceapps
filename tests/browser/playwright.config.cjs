const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  use: {
    reducedMotion: "reduce",
    launchOptions: {
      executablePath: process.env.VIEWER_CHROMIUM_PATH,
      args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
});
