export type LibraryMetadataPatch = { title?: string; tags?: string[]; collections?: string[] };
export type LibraryMetadataSelection = { assetId: string; changes: LibraryMetadataPatch };
export type LibraryMetadataHistory = { changes: { receiptId: string; status: 'applied' | 'undone'; createdAt: number; assetCount: number; firstTitle: string | null }[] };
export type LibraryMetadataFields = { title: string | null; tags: string[]; collections: { id: string; name: string }[] };
export type LibraryMetadataReceipt = {
  receiptId: string;
  status: 'prepared' | 'applied' | 'undone';
  expiresAt: number;
  undoExpiresAt: number | null;
  canUndo: boolean;
  undoReason: string | null;
  affectedResources: { kind: 'library_asset' | 'library_collection'; id: string }[];
  entries: { assetId: string; kind: string; current: LibraryMetadataFields; proposed: LibraryMetadataFields; changedFields: (keyof LibraryMetadataFields)[] }[];
};
