using Kompressr.Sdk;
using System.Globalization;

// Configure credentials through your runtime's secret store, outside the repository.
string apiKey = Environment.GetEnvironmentVariable("KOMPRESSR_API_KEY") ?? throw new InvalidOperationException("Set KOMPRESSR_API_KEY.");
var client = new KompressrClient(new() { ApiKey = apiKey });
if (args.Length < 2) throw new ArgumentException("Use: public FILE | private FILE | resume ASSET_ID | scoped CUSTOMER_USER_ID");
using var stop = new CancellationTokenSource();
Console.CancelKeyPress += (_, eventArgs) => { eventArgs.Cancel = true; stop.Cancel(); };

try
{
    switch (args[0])
    {
        case "public":
        case "private":
        {
            var accepted = await client.UploadFileAsync(args[1], new() { Visibility = args[0] }, stop.Token);
            // An ID is a recovery receipt, not a ready delivery result. Persist it in your application.
            Console.WriteLine($"Accepted asset ID: {accepted.Id}. Save this ID before waiting.");
            var ready = await client.WaitUntilReadyAsync(accepted.Id, cancellationToken: stop.Token);
            if (ready.Visibility == "public") Console.WriteLine(ready.CdnUrl);
            else
            {
                var link = await client.GeneratePrivateUrlAsync(ready.Id, cancellationToken: stop.Token);
                // Return link.Url only to the authorized caller; avoid logging signed URLs.
                Console.WriteLine($"Private file ready. Link generated; expires at {link.ExpiresAt}.");
            }
            break;
        }
        case "resume":
        {
            long id = long.Parse(args[1], CultureInfo.InvariantCulture);
            var ready = await client.WaitUntilReadyAsync(id, cancellationToken: stop.Token);
            Console.WriteLine($"Asset {ready.Id} is ready ({ready.Visibility}).");
            break;
        }
        case "scoped":
        {
            // Run only on the trusted backend with a project key authorized for administration.
            var created = await client.Platform.CreateUserAsync(new() { CustomerUserId = args[1] }, cancellationToken: stop.Token);
            var issued = await client.Platform.CreateUploadKeyAsync(created.ProjectUser.Id, new()
            { Name = "Chat uploads", AllowedVisibility = "private", Scopes = new[] { "upload", "status", "list", "private_url" } }, cancellationToken: stop.Token);
            // Store issued.ApiKey securely for this authenticated user. The API shows it only once.
            // This example deliberately does not print or persist the secret.
            var scoped = new KompressrClient(new() { ApiKey = issued.ApiKey });
            Console.WriteLine($"Created key {issued.Id} for user {created.ProjectUser.Id}. Bind this client to that user only.");
            GC.KeepAlive(scoped);
            break;
        }
        default: throw new ArgumentException("Unknown example mode.");
    }
}
catch (KompressrException error)
{
    Console.Error.WriteLine($"{error.Code}: {error.Message}");
    if (error.AssetId is { } id) Console.Error.WriteLine($"Resume with asset ID {id}.");
    if (error.MayHaveSucceeded) Console.Error.WriteLine("The write may have succeeded. Inspect its result before retrying.");
    Environment.ExitCode = 1;
}
