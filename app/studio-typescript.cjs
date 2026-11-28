const { transpileModule, ModuleKind, ScriptTarget } = require('../web/node_modules/typescript');

module.exports = function transpileStudioDependency(source) {
  return transpileModule(source, {
    fileName: this.resourcePath,
    compilerOptions: { target: ScriptTarget.ES2022, module: ModuleKind.ESNext }
  }).outputText;
};
