#!/usr/bin/env ruby
#
# generate_project.rb
# Generates Jarvis-Menubar.xcodeproj programmatically.
# Run once: ruby generate_project.rb
#

require 'xcodeproj'
require 'fileutils'

PROJECT_DIR  = File.expand_path(File.dirname(__FILE__))
PROJECT_PATH = File.join(PROJECT_DIR, "Jarvis-Menubar.xcodeproj")
SOURCE_DIR   = File.join(PROJECT_DIR, "Jarvis-Menubar")
BUNDLE_ID    = "com.pustan.jarvis.menubar"
TEAM_ID      = "724HXT72WK"  # IT Warehouse AG

FileUtils.rm_rf(PROJECT_PATH) if File.exist?(PROJECT_PATH)

project = Xcodeproj::Project.new(PROJECT_PATH)

target = project.new_target(
  :application,
  "Jarvis-Menubar",
  :osx,
  "14.0"
)

group = project.main_group.new_group("Jarvis-Menubar", SOURCE_DIR)

swift_files = Dir.glob(File.join(SOURCE_DIR, "*.swift")).sort
swift_files.each do |path|
  file_ref = group.new_file(path)
  target.source_build_phase.add_file_reference(file_ref)
end

# ── Assets catalog (created if missing) ──

assets_dir = File.join(SOURCE_DIR, "Assets.xcassets")
unless File.exist?(assets_dir)
  FileUtils.mkdir_p(File.join(assets_dir, "AppIcon.appiconset"))
  FileUtils.mkdir_p(File.join(assets_dir, "jarvis-head.imageset"))
  FileUtils.mkdir_p(File.join(assets_dir, "AccentColor.colorset"))

  File.write(
    File.join(assets_dir, "Contents.json"),
    '{"info":{"version":1,"author":"xcode"}}'
  )
  File.write(
    File.join(assets_dir, "AccentColor.colorset", "Contents.json"),
    <<~JSON
      {
        "colors": [
          {
            "idiom": "universal",
            "color": {
              "color-space": "srgb",
              "components": {
                "red": "0.29",
                "green": "0.62",
                "blue": "1.0",
                "alpha": "1.0"
              }
            }
          }
        ],
        "info": {"version": 1, "author": "xcode"}
      }
    JSON
  )
  File.write(
    File.join(assets_dir, "AppIcon.appiconset", "Contents.json"),
    <<~JSON
      {
        "images": [
          {"idiom": "mac", "size": "16x16", "scale": "1x", "filename": "icon_16x16.png"},
          {"idiom": "mac", "size": "16x16", "scale": "2x", "filename": "icon_16x16@2x.png"},
          {"idiom": "mac", "size": "32x32", "scale": "1x", "filename": "icon_32x32.png"},
          {"idiom": "mac", "size": "32x32", "scale": "2x", "filename": "icon_32x32@2x.png"},
          {"idiom": "mac", "size": "128x128", "scale": "1x", "filename": "icon_128x128.png"},
          {"idiom": "mac", "size": "128x128", "scale": "2x", "filename": "icon_128x128@2x.png"},
          {"idiom": "mac", "size": "256x256", "scale": "1x", "filename": "icon_256x256.png"},
          {"idiom": "mac", "size": "256x256", "scale": "2x", "filename": "icon_256x256@2x.png"},
          {"idiom": "mac", "size": "512x512", "scale": "1x", "filename": "icon_512x512.png"},
          {"idiom": "mac", "size": "512x512", "scale": "2x", "filename": "icon_512x512@2x.png"}
        ],
        "info": {"version": 1, "author": "xcode"}
      }
    JSON
  )
  File.write(
    File.join(assets_dir, "jarvis-head.imageset", "Contents.json"),
    <<~JSON
      {
        "images": [
          {"idiom": "universal", "scale": "1x", "filename": "jarvis-head.png"},
          {"idiom": "universal", "scale": "2x", "filename": "jarvis-head@2x.png"},
          {"idiom": "universal", "scale": "3x", "filename": "jarvis-head@3x.png"}
        ],
        "info": {"version": 1, "author": "xcode"}
      }
    JSON
  )
end
assets_ref = group.new_file(assets_dir)
target.resources_build_phase.add_file_reference(assets_ref)

# ── Info.plist ──

info_plist_path = File.join(SOURCE_DIR, "Info.plist")
info_plist = {
  "CFBundleDevelopmentRegion"           => "de",
  "CFBundleDisplayName"                 => "Jarvis",
  "CFBundleExecutable"                  => "$(EXECUTABLE_NAME)",
  "CFBundleIdentifier"                  => "$(PRODUCT_BUNDLE_IDENTIFIER)",
  "CFBundleInfoDictionaryVersion"       => "6.0",
  "CFBundleName"                        => "$(PRODUCT_NAME)",
  "CFBundlePackageType"                 => "APPL",
  "CFBundleShortVersionString"          => "1.0",
  "CFBundleVersion"                     => "1",
  # LSUIElement = 1 → agent app: no Dock icon, menu bar only.
  "LSUIElement"                         => true,
  "LSMinimumSystemVersion"              => "14.0",
  "NSMicrophoneUsageDescription"        => "Jarvis nutzt das Mikrofon um Ihre Sprachbefehle zu erkennen.",
  "NSSpeechRecognitionUsageDescription" => "Jarvis nutzt Apple Spracherkennung um Ihre Befehle zu verstehen.",
}

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
# Sandbox off — we need mic access + network + global hotkey.
ent_dict.add_element("key").text = "com.apple.security.app-sandbox"
ent_dict.add_element("false")
ent_dict.add_element("key").text = "com.apple.security.device.audio-input"
ent_dict.add_element("true")
ent_dict.add_element("key").text = "com.apple.security.network.client"
ent_dict.add_element("true")

File.open(entitlements_path, "w") do |f|
  formatter.write(ent_doc, f)
  f.puts
end
puts "Created #{entitlements_path}"

# ── Build settings ──

target.build_configurations.each do |config|
  s = config.build_settings
  s["PRODUCT_BUNDLE_IDENTIFIER"]           = BUNDLE_ID
  s["PRODUCT_NAME"]                        = "Jarvis"
  s["INFOPLIST_FILE"]                      = "Jarvis-Menubar/Info.plist"
  s["CODE_SIGN_ENTITLEMENTS"]              = "Jarvis-Menubar/Jarvis.entitlements"
  s["SWIFT_VERSION"]                       = "5.0"
  s["MACOSX_DEPLOYMENT_TARGET"]            = "14.0"
  s["GENERATE_INFOPLIST_FILE"]             = "NO"
  s["CODE_SIGN_STYLE"]                     = "Automatic"
  s["DEVELOPMENT_TEAM"]                    = TEAM_ID
  s["ENABLE_PREVIEWS"]                     = "YES"
  s["ENABLE_HARDENED_RUNTIME"]             = "YES"
  s["SWIFT_OPTIMIZATION_LEVEL"]            = (config.name == "Release" ? "-O" : "-Onone")
end

project.build_configurations.each do |config|
  s = config.build_settings
  s["ALWAYS_SEARCH_USER_PATHS"] = "NO"
  s["SWIFT_VERSION"]            = "5.0"
end

project.save
puts "Created #{PROJECT_PATH}"
puts "Done! Open Jarvis-Menubar.xcodeproj in Xcode and hit ⌘R."
