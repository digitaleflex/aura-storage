import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { emptyQueue, startUploadQueue } from "./transfer";
import type { QueueInput, QueueState, UploadQueue } from "./transfer";
import { ThroughputWindow } from "./throughput";
import { transferDeps } from "./transferDeps";
import { useAuth } from "./auth";

/** How often a per-file rate may be recomputed from observed byte deltas. */
const ITEM_RATE_WINDOW_MS = 1000;

export interface StartTransferOptions {
  csrf: string;
  folderId: string | null;
  onUpdate?: (queue: QueueState) => void;
  onAutoRetry?: (count: number) => void;
}

export interface TransfersApi {
  queue: QueueState;
  /** Browser connectivity, surfaced so the page can explain an automatic pause. */
  isOnline: boolean;
  /** Sliding-window global rate, bytes/second; 0 when nothing is running. */
  throughput: number;
  /** Per-file rates from observed byte deltas; 0 for non-uploading items. */
  itemRates: ReadonlyMap<string, number>;
  busy: boolean;
  start(entries: QueueInput[], options: StartTransferOptions): UploadQueue;
  pauseAll(): void;
  resumeAll(): void;
  cancelAll(): void;
  cancelItem(id: string): void;
  pauseItem(id: string): void;
  resumeItem(id: string): void;
  retryItem(id: string): void;
  retryFailed(): void;
  /** Empties the queue once every file has settled (no-op while unfinished). */
  clear(): void;
}

const TransfersContext = createContext<TransfersApi | null>(null);

function transferredTotal(queue: QueueState): number {
  return queue.items.reduce((sum, item) => sum + item.state.transferredBytes, 0);
}

/**
 * Owns the one live upload queue.
 *
 * The queue used to live inside the files page, so it was destroyed (and its
 * UI forgotten) as soon as the user navigated. It now sits above the router:
 * the files page starts imports, the transfers page reads and controls the
 * same queue, and the floating tray keeps working. The engine itself is
 * untouched — this provider only forwards its snapshots and actions.
 */
export function TransfersProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<QueueState>(() => emptyQueue());
  const [throughput, setThroughput] = useState(0);
  const [isOnline, setIsOnline] = useState(
    () => (typeof navigator === "undefined" ? true : navigator.onLine),
  );
  const [itemRates, setItemRates] = useState<ReadonlyMap<string, number>>(
    () => new Map(),
  );
  const { csrf } = useAuth();
  const queueRef = useRef<UploadQueue | null>(null);
  const stateRef = useRef<QueueState>(queue);
  const throughputRef = useRef(new ThroughputWindow());
  const rateHistoryRef = useRef(new Map<string, { at: number; bytes: number }>());
  const lastRatesRef = useRef(new Map<string, number>());

  const handleQueueUpdate = useCallback(
    (next: QueueState, onUpdate?: (queue: QueueState) => void) => {
      const now = Date.now();
      stateRef.current = next;
      setQueue(next);

      throughputRef.current.push(now, transferredTotal(next));
      setThroughput(next.active > 0 ? throughputRef.current.rate() : 0);

      // Per-file rate: same idea as ThroughputWindow, but per item. The engine
      // exposes no per-file speed, so it is derived from byte deltas observed
      // over at least one second (never invented when a file is not moving).
      const ids = new Set(next.items.map((item) => item.id));
      for (const id of rateHistoryRef.current.keys()) {
        if (!ids.has(id)) rateHistoryRef.current.delete(id);
      }
      for (const id of lastRatesRef.current.keys()) {
        if (!ids.has(id)) lastRatesRef.current.delete(id);
      }
      const rates = new Map<string, number>();
      for (const item of next.items) {
        if (item.state.phase !== "uploading") {
          lastRatesRef.current.set(item.id, 0);
          rates.set(item.id, 0);
          continue;
        }
        const previous = rateHistoryRef.current.get(item.id);
        const bytes = item.state.transferredBytes;
        if (!previous) {
          rateHistoryRef.current.set(item.id, { at: now, bytes });
        } else if (now - previous.at >= ITEM_RATE_WINDOW_MS) {
          const seconds = (now - previous.at) / 1000;
          const delta = bytes - previous.bytes;
          lastRatesRef.current.set(item.id, delta > 0 ? delta / seconds : 0);
          rateHistoryRef.current.set(item.id, { at: now, bytes });
        }
        rates.set(item.id, lastRatesRef.current.get(item.id) ?? 0);
      }
      setItemRates(rates);

      onUpdate?.(next);
    },
    [],
  );

  const start = useCallback(
    (entries: QueueInput[], options: StartTransferOptions): UploadQueue => {
      throughputRef.current.reset();
      rateHistoryRef.current.clear();
      lastRatesRef.current.clear();
      setThroughput(0);
      setItemRates(new Map());
      const uploadQueue = startUploadQueue(entries, transferDeps(options.csrf), {
        folderId: options.folderId,
        onUpdate: (next) => handleQueueUpdate(next, options.onUpdate),
        onAutoRetry: options.onAutoRetry,
      });
      queueRef.current = uploadQueue;
      return uploadQueue;
    },
    [handleQueueUpdate],
  );

  const pauseAll = useCallback(() => queueRef.current?.pauseAll(), []);
  const resumeAll = useCallback(() => queueRef.current?.resumeAll(), []);
  const cancelAll = useCallback(() => queueRef.current?.cancelAll(), []);
  const cancelItem = useCallback((id: string) => queueRef.current?.cancelItem(id), []);
  const pauseItem = useCallback((id: string) => queueRef.current?.pauseItem(id), []);
  const resumeItem = useCallback((id: string) => queueRef.current?.resumeItem(id), []);
  const retryItem = useCallback((id: string) => queueRef.current?.retryItem(id), []);
  const retryFailed = useCallback(() => queueRef.current?.retryFailed(), []);
  const resetQueue = useCallback(() => {
    queueRef.current = null;
    throughputRef.current.reset();
    rateHistoryRef.current.clear();
    lastRatesRef.current.clear();
    const empty = emptyQueue();
    stateRef.current = empty;
    setQueue(empty);
    setThroughput(0);
    setItemRates(new Map());
  }, []);

  const clear = useCallback(() => {
    if (!stateRef.current.finished) return;
    resetQueue();
  }, [resetQueue]);

  // A session change (logout, account switch) must not leave the previous
  // account's files visible or controllable. Abort what is running, drop the
  // in-memory queue; the backend keeps whatever was already committed.
  const previousCsrfRef = useRef<string | null>(null);
  useEffect(() => {
    const previous = previousCsrfRef.current;
    if (previous !== null && csrf !== previous) {
      queueRef.current?.cancelAll();
      queueRef.current?.dispose();
      resetQueue();
    }
    previousCsrfRef.current = csrf ?? null;
  }, [csrf, resetQueue]);

  // The engine already pauses/resumes on network events; this listener only
  // mirrors connectivity for the UI (the page must not claim the user paused).
  useEffect(() => {
    const online = () => setIsOnline(true);
    const offline = () => setIsOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  // The provider lives for the whole app, but a hard unmount (tests, HMR)
  // must not leave window listeners behind. The queue itself is not aborted:
  // leaving the page is not a cancellation request.
  useEffect(() => {
    return () => {
      queueRef.current?.dispose();
      queueRef.current = null;
    };
  }, []);

  const value = useMemo<TransfersApi>(
    () => ({
      queue,
      isOnline,
      throughput,
      itemRates,
      busy: queue.active > 0,
      start,
      pauseAll,
      resumeAll,
      cancelAll,
      cancelItem,
      pauseItem,
      resumeItem,
      retryItem,
      retryFailed,
      clear,
    }),
    [
      queue,
      isOnline,
      throughput,
      itemRates,
      start,
      pauseAll,
      resumeAll,
      cancelAll,
      cancelItem,
      pauseItem,
      resumeItem,
      retryItem,
      retryFailed,
      clear,
    ],
  );

  return (
    <TransfersContext.Provider value={value}>{children}</TransfersContext.Provider>
  );
}

export function useTransfers(): TransfersApi {
  const value = useContext(TransfersContext);
  if (!value) {
    throw new Error("useTransfers must be used inside <TransfersProvider>");
  }
  return value;
}
