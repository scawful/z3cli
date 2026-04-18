# Zelda Remote — bundled app icon

This folder contains **`Assets.xcassets`** with a complete **`AppIcon`** set (iPhone, iPad, App Store 1024×1024).

## Use in Xcode

1. In the **Project navigator**, drag **`ZeldaRemoteAppIcon/Assets.xcassets`** into your app group (copy if asked, or reference in place).
2. Select the **app target** → **General** → **App Icons and Launch Screen** → **App Icon** → choose **`AppIcon`** (from the catalog you just added).

If Xcode already created `Assets.xcassets` with an empty `AppIcon`:

- Either delete the default `AppIcon` set and drag this catalog in, **or**
- Merge: open both `AppIcon.appiconset` folders and replace the default `Contents.json` + PNGs with these files.

## Regenerating sizes from a new master

Replace `AppIcon.appiconset/AppIcon-1024.png`, then from the **z3cli repo root**:

```bash
./scripts/regenerate-ios-app-icon.sh
```

Or run the `sips` loop by hand (see script). Verify **`Contents.json`** still matches the filenames you use.
