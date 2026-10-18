# frozen_string_literal: true

require 'kompressr'

# Place this service in app/services or call it from a background job. Your
# controller authenticates the user and verifies attachment ownership first.
class KompressrAttachmentService
  def initialize(files: Kompressr::Client.new(api_key: ENV.fetch('KOMPRESSR_API_KEY')))
    @files = files
  end

  def upload(path, attachment_record:)
    accepted = @files.upload_file(path, visibility: 'private')
    attachment_record.update!(kompressr_asset_id: accepted.fetch('id'))
    accepted
  rescue Kompressr::Error => error
    if error.may_have_succeeded && error.asset_id
      attachment_record.update!(kompressr_asset_id: error.asset_id)
    end
    raise
  end

  # A retrying job resumes here using the saved ID instead of uploading again.
  def prepare(asset_id)
    @files.wait_until_ready(asset_id)
  end

  # Call only after checking that the current user can access this attachment.
  def download_url(asset_id)
    @files.generate_private_url(asset_id, expires_in: 900).fetch('private_url')
  end

  def inspect = '#<KompressrAttachmentService credentials redacted>'
end
