package com.kompressr;

import java.util.HashSet;
import java.util.Set;

/** Thread-safe cooperative cancellation. A token may cancel multiple requests. */
public final class CancellationToken {
    private boolean cancelled;
    private final Set<Runnable> callbacks = new HashSet<>();
    public synchronized boolean isCancelled() { return cancelled; }
    public void cancel() {
        Runnable[] notify;
        synchronized (this) {
            if (cancelled) return;
            cancelled = true; notify = callbacks.toArray(Runnable[]::new); callbacks.clear();
        }
        for (Runnable callback : notify) callback.run();
    }
    AutoCloseable register(Runnable callback) {
        synchronized (this) {
            if (!cancelled) { callbacks.add(callback); return () -> { synchronized (this) { callbacks.remove(callback); } }; }
        }
        callback.run(); return () -> {};
    }
}
