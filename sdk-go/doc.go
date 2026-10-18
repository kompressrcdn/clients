// Package kompressr uploads, manages and delivers files through Kompressr.
//
// Create a reusable Client with New. Every operation takes a context; timeouts
// include response reads and read retries. Save accepted upload IDs before
// waiting for processing. Writes are never automatically replayed.
package kompressr
