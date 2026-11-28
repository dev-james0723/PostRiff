// Build the standalone editor's bridge with the same dependencies as the native Rafii app.
const path = require('node:path');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const { createRequire } = require('node:module');
const web = path.resolve(__dirname, '../web');
const fromWeb = createRequire(path.join(web, 'package.json'));
const { webpack, LimitChunkCountPlugin } = fromWeb('next/dist/compiled/webpack/webpack');
const directory = path.join(__dirname, '.studio-build');
const temporary = 'studio-workspace-' + randomUUID() + '.js';

const compiler = webpack({
  context: __dirname,
  mode: 'production',
  target: 'web',
  entry: './studio-workspace.js',
  output: { path: directory, filename: temporary },
  resolve: { modules: [path.join(web, 'node_modules'), 'node_modules'], extensions: ['.ts', '.mjs', '.js', '.json'] },
  module: { rules: [{ test: /\.ts$/, include: path.join(web, 'src'), use: path.join(__dirname, 'studio-typescript.cjs') }] },
  plugins: [new LimitChunkCountPlugin({ maxChunks: 1 })],
  devtool: false,
  cache: false,
  // Preserve dependency license notices inline and avoid extra generated files.
  optimization: { minimize: false },
  performance: { hints: false }
});

compiler.run((error, stats) => {
  compiler.close((closeError) => {
    if (error || closeError || stats.hasErrors()) {
      fs.rmSync(path.join(directory, temporary), { force: true });
      console.error(error || closeError || stats.toString({ all: false, errors: true, errorDetails: true }));
      process.exitCode = 1;
      return;
    }
    // A running local editor can keep reading the previous complete bundle during a rebuild.
    const output = path.join(directory, 'studio-workspace.js');
    fs.renameSync(path.join(directory, temporary), output);
    console.log('Built Studio workspace bridge (' + fs.statSync(output).size + ' bytes).');
    if (stats.hasWarnings()) console.warn(stats.toString({ all: false, warnings: true }));
  });
});
