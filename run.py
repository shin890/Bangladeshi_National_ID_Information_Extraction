import os
import sys
import time
import subprocess

def main():
    # Detect the current python executable (pointing to the virtualenv)
    python_exe = sys.executable
    print(f"Using Python executable: {python_exe}")
    
    # Command to run FastAPI backend
    backend_cmd = [
        python_exe, "-m", "uvicorn", "backend:app", 
        "--host", "127.0.0.1", "--port", "8000",
        "--log-level", "info"
    ]
    
    # Command to run Streamlit frontend
    frontend_cmd = [
        python_exe, "-m", "streamlit", "run", "frontend.py", 
        "--server.port", "8501"
    ]
    
    print("\n--- Starting NID Extraction System ---")
    print("Starting FastAPI Backend on http://127.0.0.1:8000...")
    backend_proc = subprocess.Popen(backend_cmd)
    
    # Give the backend a brief moment to bind to the port
    time.sleep(2)
    
    print("Starting Streamlit Frontend on http://127.0.0.1:8501...")
    frontend_proc = subprocess.Popen(frontend_cmd)
    
    print("\n=======================================================")
    print("Application started successfully!")
    print("Backend API URL: http://127.0.0.1:8000")
    print("Streamlit URL:   http://127.0.0.1:8501")
    print("=======================================================")
    print("Press Ctrl+C to stop both servers...\n")
    
    try:
        while True:
            # Monitor both subprocesses
            backend_exit = backend_proc.poll()
            frontend_exit = frontend_proc.poll()
            
            if backend_exit is not None:
                print(f"Backend service stopped unexpectedly with code {backend_exit}")
                break
            if frontend_exit is not None:
                print(f"Frontend service stopped unexpectedly with code {frontend_exit}")
                break
                
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Shutting down servers...")
    finally:
        # Gracefully terminate processes
        backend_proc.terminate()
        frontend_proc.terminate()
        
        # Wait for processes to exit
        try:
            backend_proc.wait(timeout=5)
            frontend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Force killing remaining processes...")
            backend_proc.kill()
            frontend_proc.kill()
            
        print("Both servers stopped successfully.")

if __name__ == "__main__":
    main()
