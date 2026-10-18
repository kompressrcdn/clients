# frozen_string_literal: true

require 'kompressr'

module KompressrExamples
  # Persist the accepted ID through the supplied application callback before waiting.
  def self.private_upload(client, path, save_asset_id:)
    asset_id = nil
    accepted = client.upload_file(path, visibility: 'private')
    asset_id = accepted.fetch('id')
    save_asset_id.call(asset_id)
    client.wait_until_ready(asset_id)
    client.generate_private_url(asset_id, expires_in: 3600)
  rescue Kompressr::Error => error
    # A malformed upload response can still contain a trustworthy recovery ID.
    save_asset_id.call(error.asset_id) if asset_id.nil? && error.may_have_succeeded && error.asset_id
    raise
  end
end

if $PROGRAM_NAME == __FILE__
  abort 'Usage: bundle exec ruby examples/private_upload.rb FILE ASSET_ID_FILE' unless ARGV.length == 2
  begin
    client = Kompressr::Client.new(api_key: ENV.fetch('KOMPRESSR_API_KEY'))
    # Reserve a new recovery file before uploading; never overwrite an earlier ID.
    File.open(ARGV.fetch(1), File::WRONLY | File::CREAT | File::EXCL, 0o600) do |record|
      save = lambda do |id|
        record.write("#{id}\n")
        record.flush
        record.fsync
        puts "Saved asset #{id} for recovery."
      end
      result = KompressrExamples.private_upload(client, ARGV.fetch(0), save_asset_id: save)
      puts "Asset #{result.fetch('asset_id')} is ready. A private link was generated; keep it out of logs."
    end
  rescue Kompressr::Error => error
    warn "Kompressr request stopped: #{error.code}."
    warn "Resume using asset #{error.asset_id}; do not upload the file again." if error.asset_id
    warn 'The write may have succeeded. Check its outcome before retrying.' if error.may_have_succeeded
    exit 1
  end
end
