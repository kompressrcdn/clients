# frozen_string_literal: true

require 'bundler/setup'
require 'fileutils'
require 'tmpdir'
require 'rbconfig'
require 'rubygems/package'
require 'digest'

root = File.expand_path('..', __dir__)
Dir.chdir(root)

def run(*command, env: {}, directory: Dir.pwd)
  puts "+ #{command.join(' ')}"
  abort 'Verification command failed.' unless system(env, *command, chdir: directory)
end

ruby = RbConfig.ruby
source_env = { 'RUBYLIB' => File.join(root, 'lib'), 'RUBYOPT' => '-rbundler/setup', 'BUNDLE_GEMFILE' => File.join(root, 'Gemfile') }
Dir['lib/**/*.rb', 'examples/**/*.rb', 'scripts/**/*.rb', 'test/**/*.rb'].sort.each { |path| run(ruby, '-c', path) }
run(ruby, 'test/run.rb', env: source_env)

spec = Gem::Specification.load(File.join(root, 'kompressr-sdk.gemspec'))
abort 'Cannot load package specification.' unless spec
required = %w[lib/kompressr.rb README.md API.md PARITY.md CHANGELOG.md LICENSE examples/private_upload.rb examples/rails_service.rb]
abort 'Required public package files are missing.' unless required.all? { |path| spec.files.include?(path) && File.file?(path) }
artifact = File.join(root, 'pkg', "#{spec.name}-#{spec.version}.gem")
FileUtils.mkdir_p(File.dirname(artifact))
run(ruby, '-S', 'gem', 'build', 'kompressr-sdk.gemspec', '--strict', '--output', artifact)
Gem::Package.new(artifact).verify
package_spec = Gem::Package.new(artifact).spec
abort 'Package payload differs from the explicit allowlist.' unless package_spec.files.sort == spec.files.sort
abort 'Package unexpectedly includes development output.' if package_spec.files.any? { |path| path.match?(%r{\A(?:test|scripts|pkg|vendor|\.bundle)/}) }

Dir.mktmpdir('kompressr-ruby-consumer-') do |consumer|
  gem_home = File.join(consumer, 'gems')
  FileUtils.mkdir_p(gem_home)
  FileUtils.cp_r(File.join(root, 'test'), consumer)
  FileUtils.cp_r(File.join(root, 'examples'), consumer)
  # Older Rubies may need newer gems than their bundled defaults. Install the
  # resolved runtime dependency graph and the test gem from archives, never
  # from the checkout or its Bundler load paths.
  dependencies = []
  visited = {}
  collect = lambda do |dependency|
    resolved = Gem::Specification.find_by_name(dependency.name, dependency.requirement)
    next if visited[resolved.full_name]
    visited[resolved.full_name] = true
    resolved.runtime_dependencies.each { |child| collect.call(child) }
    next if resolved.default_gem?
    archive = resolved.cache_file
    abort "#{resolved.name} archive is missing; run bundle install before verification." unless File.file?(archive)
    dependencies << archive
  end
  (spec.runtime_dependencies + [Gem::Dependency.new('minitest', '>= 5.25', '< 6')]).each { |dependency| collect.call(dependency) }
  env = ENV.keys.grep(/\A(?:BUNDLE_|RUBYOPT\z|RUBYLIB\z|GEM_HOME\z|GEM_PATH\z)/).to_h { |key| [key, nil] }
  env.merge!('GEM_HOME' => gem_home, 'GEM_PATH' => gem_home, 'RUBYLIB' => nil, 'RUBYOPT' => nil)
  Bundler.with_unbundled_env do
    run(ruby, '-S', 'gem', 'install', '--local', '--no-document', *dependencies, artifact, env: env, directory: consumer)
    # Consumer runs from outside the checkout, using only the installed SDK gem.
    run(ruby, '-e', "require 'kompressr'; abort 'Wrong SDK version' unless Kompressr::VERSION == '#{spec.version}'; abort 'Source leakage' unless $LOADED_FEATURES.grep(%r{/kompressr/client.rb$}).all? { |path| path.start_with?(ENV.fetch('GEM_HOME')) }", env: env, directory: consumer)
    run(ruby, 'test/run.rb', env: env, directory: consumer)
    run(ruby, '-e', "Dir['examples/*.rb'].each { |path| require_relative path }; puts 'Installed examples loaded.'", env: env, directory: consumer)
  end
end

puts "Verified #{File.basename(artifact)} (SHA256 #{Digest::SHA256.file(artifact).hexdigest})."
