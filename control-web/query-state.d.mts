export type BoundQuery={metricIds:string[];interval:{start:string;end:string;timeZone:string};groupBy:string[];filters:{dimension:string;operator:string;values:string[]}[];comparison:string;limit:number};
export type Row={metricId:string;value:number|null;dataState:string;unit:string;dimensions?:Record<string,string>;reason?:string;outcome?:string;sourceWatermark?:string;exactSha?:string};
export type QueryResult={queryReceiptId:string;asOf:string;rows:Row[];dataState:string;executionState:string;normalizedQuery:BoundQuery;sourceVersions:Record<string,unknown>;coverage:Record<string,unknown>;warnings:string[]};
export type Run={answerText?:string;queryReceiptIds?:string[];state?:string};
export type QueryState={revision:number;status:string;attempt:{revision:number;query:BoundQuery;snapshotId:string}|null;lastGood:{result:QueryResult;query:BoundQuery;snapshotId:string;revision:number}|null;selectedReceipt:string|null;explanation:Run|null;error:string};
export const initialQueryState:QueryState;
export function signature(value:unknown):string;
export function queryReducer(state:QueryState,event:{type:string;revision?:number;query?:BoundQuery;snapshotId?:string;result?:QueryResult;error?:string;receiptId?:string;run?:Run}):QueryState;
