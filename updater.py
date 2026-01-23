import os
import sys
import json
import urllib.request
import urllib.error
import zipfile
import shutil
from pathlib import Path

class BotUpdater:
    def __init__(self):
        self.repo_owner = "Morticuss"
        self.repo_name = "Gold-trading-bot"
        self.github_api = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"
        self.version_file = ".bot_version"
        
    def get_current_version(self):
        """Get current installed version"""
        try:
            if os.path.exists(self.version_file):
                with open(self.version_file, 'r') as f:
                    return f.read().strip()
        except:
            pass
        return "0.0.0"
    
    def save_version(self, version):
        """Save version to file"""
        try:
            with open(self.version_file, 'w') as f:
                f.write(version)
        except Exception as e:
            print(f"Warning: Could not save version: {e}")
    
    def check_for_updates(self):
        """Check GitHub for latest release"""
        try:
            print("Checking for updates...", end=' ', flush=True)
            
            req = urllib.request.Request(self.github_api)
            req.add_header('User-Agent', 'Gold-Trading-Bot-Updater')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                latest_version = data['tag_name'].lstrip('v')
                download_url = None
                
                # Find the .zip asset
                for asset in data.get('assets', []):
                    if asset['name'].endswith('.zip'):
                        download_url = asset['browser_download_url']
                        break
                
                # Fallback to zipball_url if no .zip asset
                if not download_url:
                    download_url = data.get('zipball_url')
                
                print("Done!")
                
                return {
                    'available': self._compare_versions(latest_version, self.get_current_version()),
                    'latest_version': latest_version,
                    'current_version': self.get_current_version(),
                    'download_url': download_url,
                    'release_notes': data.get('body', 'No release notes available')
                }
        
        except urllib.error.URLError:
            print("Failed (no internet)")
            return None
        except Exception as e:
            print(f"Failed ({e})")
            return None
    
    def _compare_versions(self, latest, current):
        """Compare version strings (e.g., '2.0.1' vs '2.0.0')"""
        try:
            latest_parts = [int(x) for x in latest.split('.')]
            current_parts = [int(x) for x in current.split('.')]
            
            # Pad with zeros if needed
            while len(latest_parts) < 3:
                latest_parts.append(0)
            while len(current_parts) < 3:
                current_parts.append(0)
            
            return latest_parts > current_parts
        except:
            return False
    
    def download_update(self, download_url, version):
        """Download and extract update"""
        try:
            print(f"\nDownloading version {version}...", end=' ', flush=True)
            
            # Create temp directory
            temp_dir = Path("temp_update")
            temp_dir.mkdir(exist_ok=True)
            
            # Download zip
            zip_path = temp_dir / "update.zip"
            
            req = urllib.request.Request(download_url)
            req.add_header('User-Agent', 'Gold-Trading-Bot-Updater')
            
            with urllib.request.urlopen(req, timeout=60) as response:
                with open(zip_path, 'wb') as f:
                    f.write(response.read())
            
            print("Done!")
            print("Extracting files...", end=' ', flush=True)
            
            # Extract zip
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            print("Done!")
            
            # Find the extracted folder (GitHub adds repo name prefix)
            extracted_folders = [f for f in temp_dir.iterdir() if f.is_dir()]
            if not extracted_folders:
                raise Exception("No extracted folder found")
            
            source_dir = extracted_folders[0]
            
            # Files to update
            files_to_update = [
                'gold_bot.py',
                'requirements.txt',
                'README.md',
                'CHANGELOG.md',
                'LICENSE',
                'updater.py'
            ]
            
            # Backup current version
            current_version = self.get_current_version()
            if current_version != "0.0.0":
                backup_dir = Path(f"backup_{current_version}")
                backup_dir.mkdir(exist_ok=True)
                
                print(f"Backing up current version...", end=' ', flush=True)
                for file in files_to_update:
                    if os.path.exists(file):
                        try:
                            shutil.copy2(file, backup_dir / file)
                        except:
                            pass
                print("Done!")
            
            # Copy new files
            print("Installing update...", end=' ', flush=True)
            updated_count = 0
            for file in files_to_update:
                source_file = source_dir / file
                if source_file.exists():
                    shutil.copy2(source_file, file)
                    updated_count += 1
            
            print(f"Done! ({updated_count} files updated)")
            
            # Save new version
            self.save_version(version)
            
            # Cleanup
            shutil.rmtree(temp_dir)
            
            print(f"\n✓ Successfully updated to version {version}!")
            if current_version != "0.0.0":
                print(f"✓ Backup saved to: backup_{current_version}/")
            return True
            
        except Exception as e:
            print(f"\n✗ Update failed: {e}")
            # Cleanup on failure
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return False
    
    def run(self):
        """Main update check and install flow"""
        current_version = self.get_current_version()
        is_first_run = (current_version == "0.0.0")
        
        # Silent first run - just set up version tracking
        if is_first_run:
            update_info = self.check_for_updates()
            if update_info:
                self.save_version(update_info['latest_version'])
            return True
        
        # Normal update check for existing users
        print("="*70)
        print("GOLD TRADING BOT - UPDATE CHECKER".center(70))
        print("="*70)
        print()
        
        update_info = self.check_for_updates()
        
        if update_info is None:
            print("Continuing with current version...\n")
            return True
        
        if not update_info['available']:
            print(f"✓ You have the latest version ({current_version})\n")
            return True
        
        # New update available
        print(f"🆕 New version available!")
        print(f"   Current: {update_info['current_version']}")
        print(f"   Latest:  {update_info['latest_version']}")
        print()
        
        # Show release notes (first 10 lines)
        notes_lines = update_info['release_notes'].split('\n')[:10]
        print("Release Notes:")
        print("-" * 70)
        for line in notes_lines:
            print(line)
        if len(update_info['release_notes'].split('\n')) > 10:
            print("...")
        print("-" * 70)
        print()
        
        # Ask user
        while True:
            response = input("Download and install update? (y/n): ").lower().strip()
            if response in ['y', 'n']:
                break
            print("Please enter 'y' or 'n'")
        
        if response != 'y':
            print("\nUpdate skipped. Continuing with current version...\n")
            return True
        
        # Download and install
        success = self.download_update(
            update_info['download_url'],
            update_info['latest_version']
        )
        
        if success:
            print("\nStarting bot...\n")
            return True
        else:
            print("\nUpdate failed. Continuing with current version...\n")
            return True

def main():
    updater = BotUpdater()
    updater.run()

if __name__ == "__main__":
    main()