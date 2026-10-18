// Provision a scoped runtime key, or explicitly rotate/revoke an existing key.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"

	kompressr "github.com/kompressrcdn/clients/sdk-go"
)

func run() error {
	customer := flag.String("customer", "", "stable authenticated application user ID (create only)")
	user := flag.String("user", "", "project user UUID (rotate/revoke)")
	key := flag.String("key", "", "key-record UUID (rotate/revoke)")
	action := flag.String("action", "create", "create, rotate or revoke")
	output := flag.String("out", "", "new private file for a one-time issued key")
	flag.Parse()
	if *action != "create" && *action != "rotate" && *action != "revoke" {
		return fmt.Errorf("action must be create, rotate or revoke")
	}
	if *action == "create" && *customer == "" {
		return fmt.Errorf("create requires -customer")
	}
	if *action != "create" && (*user == "" || *key == "") {
		return fmt.Errorf("rotate/revoke require -user and -key")
	}
	// Open the destination before issuing a nonrecoverable secret. O_EXCL prevents
	// accidental overwrites. Keep this file outside your repository.
	var file *os.File
	var err error
	if *action != "revoke" {
		if *output == "" {
			return fmt.Errorf("create/rotate require -out outside the repository")
		}
		file, err = os.OpenFile(*output, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return err
		}
		defer file.Close()
	}
	client, err := kompressr.NewPlatform(kompressr.Config{APIKey: os.Getenv("KOMPRESSR_API_KEY")})
	if err != nil {
		return err
	}
	defer client.CloseIdleConnections()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	var issued kompressr.IssuedKey
	switch *action {
	case "create":
		identity, err := client.CreateUser(ctx, kompressr.CreateUserOptions{CustomerUserID: *customer}, kompressr.RequestOptions{})
		if err != nil {
			return err
		}
		*user = identity.ProjectUser.ID
		issued, err = client.CreateUploadKey(ctx, *user, kompressr.CreateKeyOptions{Name: "Application runtime", Scopes: []kompressr.UploadScope{kompressr.ScopeUpload, kompressr.ScopeStatus, kompressr.ScopeList, kompressr.ScopePrivateURL}, AllowedVisibility: kompressr.Private}, kompressr.RequestOptions{})
	case "rotate":
		issued, err = client.RotateUploadKey(ctx, *user, *key, kompressr.RequestOptions{})
	case "revoke":
		err = client.RevokeUploadKey(ctx, *user, *key, kompressr.RequestOptions{})
	}
	if err != nil {
		return err
	}
	if *action == "revoke" {
		fmt.Println("Key revoked.")
		return nil
	}
	if err = json.NewEncoder(file).Encode(issued); err != nil {
		return fmt.Errorf("issued key %s could not be saved; revoke it before issuing another", issued.ID)
	}
	if err = file.Sync(); err != nil {
		return fmt.Errorf("issued key %s could not be durably saved; verify storage or revoke it", issued.ID)
	}
	fmt.Printf("Project user: %s\nKey record: %s\nOne-time credential saved to the private output file.\n", *user, issued.ID)
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
