/** Lane F state module: artifact state machine, persisted view state, selection memory and tab-local registries. */
export { INITIAL_ARTIFACT_STATE, reduceArtifact, renderOf, statusLine } from './artifact-machine';
export type { ArtifactAction, ArtifactPhase, ArtifactRender, ArtifactViewState, UiArtifactViewV1, UiAttemptView } from './artifact-machine';
export { applyUiPatch, persistableKeys, selectionValue, SELECTION_KEY, UiStateController } from './persisted-state';
export type { DeclaredState, SelectionItem, StoredState, UiStateControllerOptions } from './persisted-state';
export { UiArtifactStateContext, useUiArtifactState } from './context';
export type { UiArtifactStateBridge } from './context';
export { useRecordSelection } from './selection';
export type { RecordSelection } from './selection';
export { clearUiContext, currentUiContext, enterUiScope, isFresh, markFresh, noteUiInteraction, onUiScopeChange, presentationKey, setUiContext } from './registry';
