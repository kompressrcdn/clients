# PHP examples

Run `composer install` in the package directory. Set `KOMPRESSR_API_KEY` through your secret manager or shell environment without pasting its value into scripts. Set `KOMPRESSR_PROJECT_ID` when listing uploads. To run these scripts against an installed package, set `KOMPRESSR_AUTOLOAD` to your application's Composer autoloader.

- `public-upload.php FILE NEW_PRIVATE_RECEIPT` saves the accepted ID, waits, and prints the public URL.
- `private-upload.php FILE NEW_PRIVATE_RECEIPT` saves the ID and generates a private link without printing it.
- `resume.php PRIVATE_RECEIPT` resumes the existing asset, without uploading it again.
- `scoped-key.php CUSTOMER_USER_ID` provisions a project user and key using a project credential. Integrate your secure key store before using this in a persistent application; the example deliberately does not save or print the secret.

The receipt argument must be a new file in a private directory outside the checkout. Example receipts use mode 0600 and are flushed before waiting. In a deployed application, persist the accepted ID in your job/database record and handle storage failures before scheduling another upload. Keep all generated private links out of logs.

These examples perform real operations when you run them with credentials. Use a dedicated test project, keep the receipts, and delete only assets created by your tests. The automated verifier lints examples and exercises equivalent flows through local HTTP fixtures; it does not execute examples against the service.
