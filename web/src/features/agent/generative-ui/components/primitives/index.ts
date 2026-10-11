'use client';
/** Renderers of lane C's primitives, keyed by the spec names in `component-specs.ts` (one renderer per spec). */
import type { JourneyRenderers } from '../../core/component-types';
import { ActionButton } from './action-button';
import { AssetPreview } from './asset-preview';
import { ToolBoundChart } from './chart';
import { Comparison, Metric, TaskStatus, Timeline, ToolBoundTable } from './data';
import { Button, DateRange, Form, Select, TextField } from './inputs';
import { Accordion, AccordionItem, Card, EvidenceLink, Grid, RafiiRoot, Section, Stack, TabItem, Tabs, Text } from './layout';
import { SelectionList } from './selection';
import { EmptyState, ErrorState, LoadingState } from './states';

export const PRIMITIVE_RENDERERS: JourneyRenderers = {
  RafiiRoot,
  Stack,
  Grid,
  Section,
  Card,
  Tabs,
  TabItem,
  Accordion,
  AccordionItem,
  Text,
  EvidenceLink,
  EmptyState,
  LoadingState,
  ErrorState,
  ToolBoundTable,
  ToolBoundChart,
  Metric,
  Timeline,
  Comparison,
  TaskStatus,
  SelectionList,
  AssetPreview,
  Form,
  TextField,
  Select,
  DateRange,
  Button,
  ActionButton,
};

export { AssetPreviewView, previewRouteAllowed, previewUrlAllowed, type AssetPreviewItem, type AssetPreviewSize } from './asset-preview';
export { collectActionInputs } from './action-button';
export { useFormValues, useRafiiForm, type RafiiFormContextValue } from './inputs';
export { safeLinkTarget } from './layout';
export { Children, LoadingRows, QueryStateNote, SourceMeta, StatusBadge, statusText, Unrenderable } from './shared';
