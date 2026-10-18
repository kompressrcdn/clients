// Upload a file, or resume a saved asset ID, with bounded processing waits.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"

	kompressr "github.com/kompressrcdn/clients/sdk-go"
)

func run() error {
	file := flag.String("file", "", "local file to upload")
	resume := flag.Int64("resume", 0, "saved asset ID; skips uploading")
	private := flag.Bool("private", false, "upload privately")
	showLink := flag.Bool("show-url", false, "print the delivery URL to this terminal")
	flag.Parse()
	if (*file == "") == (*resume == 0) {
		return fmt.Errorf("supply exactly one of -file or -resume")
	}
	client, err := kompressr.New(kompressr.Config{APIKey: os.Getenv("KOMPRESSR_API_KEY")})
	if err != nil {
		return err
	}
	defer client.CloseIdleConnections()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	id := *resume
	if id == 0 {
		visibility := kompressr.Public
		if *private {
			visibility = kompressr.Private
		}
		accepted, err := client.UploadFile(ctx, *file, kompressr.UploadOptions{Visibility: visibility})
		if err != nil {
			return err
		}
		id = accepted.ID
		// Persist this ID in your database before polling in an application. This
		// command displays it immediately so a later run can use -resume.
		fmt.Printf("Accepted asset %d. Save this ID before continuing.\n", id)
	}
	ready, err := client.WaitUntilReady(ctx, id, kompressr.WaitOptions{})
	if err != nil {
		return err
	}
	fmt.Printf("Asset %d is ready (%s).\n", id, ready.Visibility)
	if *showLink {
		delivery := ready.CDNURL
		if ready.Visibility == kompressr.Private {
			signed, err := client.GeneratePrivateURL(ctx, id, kompressr.PrivateURLOptions{})
			if err != nil {
				return err
			}
			delivery = signed.PrivateURL
		}
		// Private links grant access. This is explicit local output, not routine logs.
		fmt.Println(delivery)
	}
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		var failure *kompressr.Error
		if errors.As(err, &failure) {
			if failure.AssetID != 0 {
				fmt.Fprintf(os.Stderr, "Saved asset ID: %d; resume with -resume %d.\n", failure.AssetID, failure.AssetID)
			}
			if failure.MayHaveSucceeded {
				fmt.Fprintln(os.Stderr, "The write outcome is uncertain. Inspect it before repeating the write.")
			}
		}
		os.Exit(1)
	}
}
