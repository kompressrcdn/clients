# frozen_string_literal: true

require_relative 'lib/kompressr/version'

Gem::Specification.new do |spec|
  spec.name = 'kompressr-sdk'
  spec.version = Kompressr::VERSION
  spec.authors = ['Kompressr']
  spec.summary = 'Official Ruby SDK for Kompressr file and platform APIs.'
  spec.description = 'Upload, wait for processing, sign private links and manage scoped identities using a framework-independent Ruby client.'
  spec.homepage = 'https://kompressr.com'
  spec.license = 'MIT'
  spec.required_ruby_version = '>= 3.2'
  spec.metadata = {
    'source_code_uri' => 'https://github.com/kompressrcdn/clients/tree/main/sdk-ruby',
    'documentation_uri' => 'https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/README.md',
    'changelog_uri' => 'https://github.com/kompressrcdn/clients/blob/main/sdk-ruby/CHANGELOG.md',
    'bug_tracker_uri' => 'https://github.com/kompressrcdn/clients/issues',
    'allowed_push_host' => 'https://rubygems.org',
    'rubygems_mfa_required' => 'true'
  }
  spec.files = Dir.chdir(__dir__) do
    (Dir['lib/**/*.rb', 'examples/**/*.rb'] + %w[README.md API.md PARITY.md CHANGELOG.md LICENSE]).sort
  end
  spec.require_paths = ['lib']
  spec.add_dependency 'json', '>= 2.7', '< 3'
  spec.add_dependency 'openssl', '>= 3.2', '< 5'
  spec.add_dependency 'uri', '>= 0.13', '< 2'
  spec.add_dependency 'time', '>= 0.3', '< 1'
  spec.add_dependency 'ipaddr', '>= 1.2.5', '< 2'
  spec.add_dependency 'securerandom', '>= 0.3', '< 1'
end
