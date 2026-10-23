//go:build ignore

// Verify the module and install its ZIP in an isolated consumer using a local
// file proxy. No registry, account or live Kompressr service is required.
package main

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	kompressr "github.com/kompressrcdn/clients/sdk-go"
)

const module = "github.com/kompressrcdn/clients/sdk-go"
const version = "v" + kompressr.Version

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func command(dir string, env []string, args ...string) {
	fmt.Println("go", strings.Join(args, " "))
	cmd := exec.Command("go", args...)
	cmd.Dir = dir
	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	must(cmd.Run())
}
func main() {
	root, e := os.Getwd()
	must(e)
	raw, e := os.ReadFile(filepath.Join(root, "go.mod"))
	must(e)
	if !strings.HasPrefix(string(raw), "module "+module+"\n") {
		must(fmt.Errorf("run from sdk-go"))
	}
	command(root, os.Environ(), "build", "./...")
	command(root, os.Environ(), "vet", "./...")
	command(root, os.Environ(), "test", "-race", "-count=1", "./...")
	temp, e := os.MkdirTemp("", "kompressr-go-consumer-")
	must(e)
	defer os.RemoveAll(temp)
	proxy := filepath.Join(temp, "proxy")
	target := filepath.Join(proxy, filepath.FromSlash(module), "@v")
	must(os.MkdirAll(target, 0700))
	archive := new(bytes.Buffer)
	zw := zip.NewWriter(archive)
	files := 0
	must(filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == root {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		if entry.IsDir() {
			if strings.HasPrefix(entry.Name(), ".") {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("unexpected symlink in module: %s", rel)
		}
		ext := filepath.Ext(rel)
		if ext != ".go" && ext != ".md" && rel != "go.mod" && rel != "LICENSE" && filepath.ToSlash(rel) != "testdata/file-lifecycle.json" {
			return fmt.Errorf("unexpected package file: %s", rel)
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		file, err := zw.Create(module + "@" + version + "/" + filepath.ToSlash(rel))
		if err != nil {
			return err
		}
		if _, err = file.Write(b); err != nil {
			return err
		}
		files++
		return nil
	}))
	must(zw.Close())
	if output := os.Getenv("KOMPRESSR_VERIFY_ARTIFACT_DIR"); output != "" {
		must(os.MkdirAll(output, 0700))
		destination := filepath.Join(output, "kompressr-go-"+version+".zip")
		must(os.WriteFile(destination, archive.Bytes(), 0600))
		fmt.Println("Module archive:", destination)
	}
	must(os.WriteFile(filepath.Join(target, version+".zip"), archive.Bytes(), 0600))
	must(os.WriteFile(filepath.Join(target, version+".mod"), raw, 0600))
	must(os.WriteFile(filepath.Join(target, version+".info"), []byte(`{"Version":"`+version+`","Time":"2026-01-01T00:00:00Z"}`), 0600))
	must(os.WriteFile(filepath.Join(target, "list"), []byte(version+"\n"), 0600))
	consumer := filepath.Join(temp, "consumer")
	must(os.MkdirAll(consumer, 0700))
	must(os.WriteFile(filepath.Join(consumer, "go.mod"), []byte("module example.test/consumer\n\ngo 1.24.0\n\nrequire "+module+" "+version+"\n"), 0600))
	must(os.WriteFile(filepath.Join(consumer, "main.go"), []byte(consumerSource), 0600))
	env := []string{}
	for _, v := range os.Environ() {
		if !strings.HasPrefix(v, "GOPROXY=") && !strings.HasPrefix(v, "GOSUMDB=") && !strings.HasPrefix(v, "GOMODCACHE=") && !strings.HasPrefix(v, "GOWORK=") && !strings.HasPrefix(v, "GONOPROXY=") && !strings.HasPrefix(v, "GONOSUMDB=") && !strings.HasPrefix(v, "GOPRIVATE=") {
			env = append(env, v)
		}
	}
	env = append(env, "GOPROXY=file://"+filepath.ToSlash(proxy), "GOSUMDB=off", "GOMODCACHE="+filepath.Join(temp, "module-cache"), "GOWORK=off", "GONOPROXY=none", "GONOSUMDB=none", "GOPRIVATE=")
	command(consumer, env, "mod", "download", module)
	command(consumer, env, "run", ".")
	fmt.Printf("Verified %d files in %s@%s ZIP; isolated installed consumer passed.\n", files, module, version)
}

const consumerSource = `package main

import (
 "context"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "net/http"
 "net/http/httptest"

 k "github.com/kompressrcdn/clients/sdk-go"
)

func main() {
 calls := 0
 server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
  calls++
  if r.Header.Get("Authorization") != "Bearer fixture-key" { panic("wrong auth") }
  io.Copy(io.Discard, r.Body)
  data := map[string]any{
   "id":42, "asset_id":42, "status":"processed", "deletion_status":"active",
   "visibility":"public", "original_name":"x.png", "original_size":3,
   "asset_type":"image", "cdn_url":"https://cdn.example/ready.webp",
   "kompressd_size":2, "savings_percent":33, "can_generate_private_url":false,
  }
  var response any = data
  if calls == 3 {
   data["status"] = "failed"
   raw, _ := json.Marshal(data)
   response = json.RawMessage(append(append(raw[:len(raw)-1], ','), []byte("\"Status\":\"processed\"}")...))
  }
  json.NewEncoder(w).Encode(map[string]any{"success":true, "data":response})
 }))
 defer server.Close()
 client, err := k.New(k.Config{APIKey:"fixture-key", APIBaseURL:server.URL})
 if err != nil { panic(err) }
 defer client.CloseIdleConnections()
 ctx := context.Background()
 accepted, err := client.UploadBytes(ctx, []byte("abc"), "x.png", k.UploadOptions{})
 if err != nil { panic(err) }
 ready, err := client.WaitUntilReady(ctx, accepted.ID, k.WaitOptions{})
 if err != nil || ready.ID != 42 || calls != 2 { panic("consumer lifecycle failed") }
 fmt.Println("Installed module upload and readiness passed.")
 _, err = client.Platform.CreateUploadKey(ctx, "660e8400-e29b-41d4-a716-446655440002", k.CreateKeyOptions{Name:"Runtime", Scopes:[]k.UploadScope{}}, k.RequestOptions{})
 var failure *k.Error
 if !errors.As(err, &failure) || failure.Code != "INVALID_ARGUMENT" || failure.MayHaveSucceeded || calls != 2 { panic("consumer empty-scope validation failed") }
 _, err = client.WaitUntilReady(ctx, accepted.ID, k.WaitOptions{})
 if !errors.As(err, &failure) || failure.Code != "PROCESSING_FAILED" || failure.AssetID != 42 || calls != 3 { panic("consumer response alias overrode terminal processing status") }
 fmt.Println("Installed module exact-field and empty-scope regressions passed.")
}
`
