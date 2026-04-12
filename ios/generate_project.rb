#!/usr/bin/env ruby
#
# generate_project.rb
# Generates the Jarvis.xcodeproj programmatically using the xcodeproj gem.
# Run once: ruby generate_project.rb
#

require 'xcodeproj'
require 'fileutils'

PROJECT_DIR  = File.expand_path(File.dirname(__FILE__))
PROJECT_PATH = File.join(PROJECT_DIR, "Jarvis.xcodeproj")
SOURCE_DIR   = File.join(PROJECT_DIR, "Jarvis")
BUNDLE_ID    = "com.pustan.jarvis"
TEAM_ID      = "724HXT72WK"  # IT Warehouse AG

# Clean slate
FileUtils.rm_rf(PROJECT_PATH) if File.exist?(PROJECT_PATH)

project = Xcodeproj::Project.new(PROJECT_PATH)

# ── Main target ──

target = project.new_target(
  :application,
  "Jarvis",
  :ios,
  "17.0"
)

# ── Add Swift source files ──

group = project.main_group.new_group("Jarvis", SOURCE_DIR)

swift_files = Dir.glob(File.join(SOURCE_DIR, "*.swift")).sort
swift_files.each do |path|
  file_ref = group.new_file(path)
  target.source_build_phase.add_file_reference(file_ref)
end

# ── Add Assets catalog (create if missing) ──

assets_dir = File.join(SOURCE_DIR, "Assets.xcassets")
unless File.exist?(assets_dir)
  FileUtils.mkdir_p(File.join(assets_dir, "AppIcon.appiconset"))
  File.write(
    File.join(assets_dir, "Contents.json"),
    '{"info":{"version":1,"author":"xcode"}}'
  )
  File.write(
    File.join(assets_dir, "AppIcon.appiconset", "Contents.json"),
    '{"images":[{"idiom":"universal","platform":"ios","size":"1024x1024"}],"info":{"version":1,"author":"xcode"}}'
  )
end
assets_ref = group.new_file(assets_dir)
target.resources_build_phase.add_file_reference(assets_ref)

# ── Info.plist ──

info_plist_path = File.join(SOURCE_DIR, "Info.plist")
info_plist = {
  "CFBundleDevelopmentRegion"            => "de",
  "CFBundleDisplayName"                  => "Jarvis",
  "CFBundleExecutable"                   => "$(EXECUTABLE_NAME)",
  "CFBundleIdentifier"                   => "$(PRODUCT_BUNDLE_IDENTIFIER)",
  "CFBundleInfoDictionaryVersion"        => "6.0",
  "CFBundleName"                         => "$(PRODUCT_NAME)",
  "CFBundlePackageType"                  => "APPL",
  "CFBundleShortVersionString"           => "1.0",
  "CFBundleVersion"                      => "1",
  "LSRequiresIPhoneOS"                   => true,
  "UILaunchScreen"                       => {},
  "UISupportedInterfaceOrientations"     => ["UIInterfaceOrientationPortrait"],
  "UIRequiredDeviceCapabilities"         => ["armv7"],
  "NSMicrophoneUsageDescription"         => "Jarvis nutzt das Mikrofon um Ihre Sprachbefehle zu erkennen.",
  "NSSpeechRecognitionUsageDescription"  => "Jarvis nutzt Apple Spracherkennung um Ihre Befehle zu verstehen.",
  "NSLocationWhenInUseUsageDescription"  => "Jarvis nutzt Ihren Standort um aktuelles Wetter anzuzeigen.",
  # Push Notifications require an explicit App ID on developer.apple.com.
  # Uncomment after creating it:
  # "UIBackgroundModes"                    => ["remote-notification"],
}

# Write as XML plist
require 'rexml/document'
plist_doc = REXML::Document.new
plist_doc << REXML::XMLDecl.new("1.0", "UTF-8")
plist_doc << REXML::DocType.new('plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"')
plist_el = plist_doc.add_element("plist", "version" => "1.0")

def add_plist_value(parent, value)
  case value
  when Hash
    dict = parent.add_element("dict")
    value.each do |k, v|
      dict.add_element("key").text = k
      add_plist_value(dict, v)
    end
  when Array
    arr = parent.add_element("array")
    value.each { |v| add_plist_value(arr, v) }
  when String
    parent.add_element("string").text = value
  when TrueClass
    parent.add_element("true")
  when FalseClass
    parent.add_element("false")
  when Integer
    parent.add_element("integer").text = value.to_s
  end
end

add_plist_value(plist_el, info_plist)

formatter = REXML::Formatters::Pretty.new(4)
formatter.compact = true
File.open(info_plist_path, "w") do |f|
  formatter.write(plist_doc, f)
  f.puts
end
puts "Created #{info_plist_path}"

# ── Entitlements ──

entitlements_path = File.join(SOURCE_DIR, "Jarvis.entitlements")
ent_doc = REXML::Document.new
ent_doc << REXML::XMLDecl.new("1.0", "UTF-8")
ent_doc << REXML::DocType.new('plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"')
ent_plist = ent_doc.add_element("plist", "version" => "1.0")
ent_dict = ent_plist.add_element("dict")
# Push entitlement requires explicit App ID. Uncomment after setup:
# ent_dict.add_element("key").text = "aps-environment"
# ent_dict.add_element("string").text = "development"

File.open(entitlements_path, "w") do |f|
  formatter.write(ent_doc, f)
  f.puts
end
puts "Created #{entitlements_path}"

# ── Build settings ──

target.build_configurations.each do |config|
  s = config.build_settings
  s["PRODUCT_BUNDLE_IDENTIFIER"]      = BUNDLE_ID
  s["INFOPLIST_FILE"]                  = "Jarvis/Info.plist"
  # Entitlements only needed once push is configured:
  # s["CODE_SIGN_ENTITLEMENTS"]          = "Jarvis/Jarvis.entitlements"
  s["SWIFT_VERSION"]                   = "5.0"
  s["IPHONEOS_DEPLOYMENT_TARGET"]      = "17.0"
  s["TARGETED_DEVICE_FAMILY"]          = "1"  # iPhone only
  s["ASSETCATALOG_COMPILER_APPICON_NAME"] = "AppIcon"
  s["GENERATE_INFOPLIST_FILE"]         = "NO"
  s["CODE_SIGN_STYLE"]                 = "Automatic"
  s["DEVELOPMENT_TEAM"]                = TEAM_ID || ""
  s["ENABLE_PREVIEWS"]                 = "YES"

  if config.name == "Release"
    s["SWIFT_OPTIMIZATION_LEVEL"] = "-O"
  else
    s["SWIFT_OPTIMIZATION_LEVEL"] = "-Onone"
  end
end

# Project-level build settings
project.build_configurations.each do |config|
  s = config.build_settings
  s["ALWAYS_SEARCH_USER_PATHS"]  = "NO"
  s["SWIFT_VERSION"]             = "5.0"
end

# ── Save ──

project.save
puts "Created #{PROJECT_PATH}"
puts "Done! Open Jarvis.xcodeproj in Xcode, select your Team, and hit ⌘R."
