import os
import time
import hashlib
import shutil
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from github import Github
import threading
from datetime import datetime

class FolderMonitor:
    def __init__(self, local_folder, github_token, repo_name, branch="main"):
        self.local_folder = Path(local_folder)
        self.github_token = github_token
        self.repo_name = repo_name
        self.branch = branch
        self.last_sync = {}
        self.sync_lock = threading.Lock()
        self.sync_queue = set()
        self.sync_timer = None
        
        # Initialize GitHub connection
        self.g = Github(github_token)
        self.repo = self.g.get_repo(repo_name)
        
        # Create local folder if it doesn't exist
        self.local_folder.mkdir(parents=True, exist_ok=True)
        
        print(f"📁 Monitoring folder: {self.local_folder}")
        print(f"🔗 Connected to GitHub repo: {self.repo_name}")
        
    def get_file_hash(self, file_path):
        """Calculate MD5 hash of a file"""
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"⚠️  Error calculating hash for {file_path}: {e}")
            return None
    
    def get_github_file_path(self, local_path):
        """Convert local path to GitHub path"""
        relative_path = Path(local_path).relative_to(self.local_folder)
        return str(relative_path).replace("\\", "/")
    
    def upload_file(self, file_path):
        """Upload or update a file on GitHub"""
        try:
            github_path = self.get_github_file_path(file_path)
            
            # Read file content
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Check if file exists on GitHub
            try:
                contents = self.repo.get_contents(github_path, ref=self.branch)
                # Update existing file
                self.repo.update_file(
                    path=github_path,
                    message=f"Update {github_path} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content=content,
                    sha=contents.sha,
                    branch=self.branch
                )
                print(f"✅ Updated: {github_path}")
            except Exception:
                # Create new file
                self.repo.create_file(
                    path=github_path,
                    message=f"Add {github_path} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content=content,
                    branch=self.branch
                )
                print(f"➕ Created: {github_path}")
                
        except Exception as e:
            print(f"❌ Error uploading {file_path}: {e}")
    
    def delete_file(self, file_path):
        """Delete a file from GitHub"""
        try:
            github_path = self.get_github_file_path(file_path)
            contents = self.repo.get_contents(github_path, ref=self.branch)
            
            self.repo.delete_file(
                path=github_path,
                message=f"Delete {github_path} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                sha=contents.sha,
                branch=self.branch
            )
            print(f"🗑️  Deleted: {github_path}")
            
        except Exception as e:
            print(f"❌ Error deleting {file_path}: {e}")
    
    def sync_changes(self):
        """Process queued changes"""
        with self.sync_lock:
            if not self.sync_queue:
                return
                
            print(f"🔄 Syncing {len(self.sync_queue)} changes...")
            
            # Process each queued item
            for item in list(self.sync_queue):
                path, action = item
                try:
                    if action == "deleted":
                        if Path(path).exists():
                            continue  # File still exists, skip deletion
                        self.delete_file(path)
                    elif Path(path).exists():
                        self.upload_file(path)
                except Exception as e:
                    print(f"❌ Sync error for {path}: {e}")
            
            self.sync_queue.clear()
            print("✅ Sync completed")
    
    def queue_sync(self, file_path, action):
        """Queue a file for sync after delay"""
        with self.sync_lock:
            self.sync_queue.add((str(file_path), action))
            
            # Cancel existing timer
            if self.sync_timer:
                self.sync_timer.cancel()
            
            # Set new timer for 30 seconds
            self.sync_timer = threading.Timer(30.0, self.sync_changes)
            self.sync_timer.start()
    
    def process_existing_files(self):
        """Process all existing files on startup"""
        print("🔍 Processing existing files...")
        for file_path in self.local_folder.rglob("*"):
            if file_path.is_file():
                self.upload_file(file_path)
        print("✅ Existing files processed")

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, monitor):
        self.monitor = monitor
    
    def on_modified(self, event):
        if not event.is_directory:
            print(f"✏️  Modified: {event.src_path}")
            self.monitor.queue_sync(event.src_path, "modified")
    
    def on_created(self, event):
        if not event.is_directory:
            print(f"➕ Created: {event.src_path}")
            self.monitor.queue_sync(event.src_path, "created")
    
    def on_deleted(self, event):
        print(f"🗑️  Deleted: {event.src_path}")
        self.monitor.queue_sync(event.src_path, "deleted")
    
    def on_moved(self, event):
        print(f"➡️  Moved: {event.src_path} → {event.dest_path}")
        if not event.is_directory:
            # Delete old file
            self.monitor.queue_sync(event.src_path, "deleted")
            # Upload new file
            self.monitor.queue_sync(event.dest_path, "created")

def main():
    # Configuration - UPDATE THESE VALUES
    LOCAL_FOLDER = "C:/path/to/your/folder"  # Change this to your folder path
    GITHUB_TOKEN = "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"   # Get from GitHub Settings → Developer settings → Personal access tokens
    REPO_NAME = "rdp269-bot/chat-server"         # Format: username/repo-name
    
    # Create monitor instance
    monitor = FolderMonitor(LOCAL_FOLDER, GITHUB_TOKEN, REPO_NAME)
    
    # Process existing files
    monitor.process_existing_files()
    
    # Set up file watcher
    event_handler = FileChangeHandler(monitor)
    observer = Observer()
    observer.schedule(event_handler, str(monitor.local_folder), recursive=True)
    
    # Start monitoring
    observer.start()
    print("👀 Folder monitoring started. Press Ctrl+C to stop.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping monitor...")
        observer.stop()
        # Force sync any pending changes
        if monitor.sync_timer:
            monitor.sync_timer.cancel()
        monitor.sync_changes()
    
    observer.join()

if __name__ == "__main__":
    main()
