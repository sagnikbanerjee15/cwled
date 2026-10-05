#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Check if we are running a bundled module/tool in a frozen environment or subprocess
if len(sys.argv) > 2 and sys.argv[1] == '--run-module':
    module_name = sys.argv[2]
    # Remove the command name and '--run-module <module>' so the module's argparser parses correctly
    sys.argv = [sys.argv[0]] + sys.argv[3:]
    
    # Set up sys.path like we do for running normally in frozen environment
    if getattr(sys, 'frozen', False) or 'RESOURCEPATH' in os.environ:
        try:
            import cwled
            sys.path.append(os.path.dirname(cwled.__file__))
        except Exception:
            pass
            
    if module_name == 'cwltool':
        from cwltool.main import run
        sys.exit(run())
    elif module_name == 'cwlpack':
        from sbpack.pack import localpack
        sys.exit(localpack())
    elif module_name == 'cwl-upgrader':
        from cwlupgrader.main import main as upgrade_main
        sys.exit(upgrade_main())
    elif module_name == 'cwl-explode':
        from cwlformat.explode import main as explode_main
        sys.exit(explode_main())
    else:
        print(f"Error: Unknown bundled module '{module_name}'")
        sys.exit(1)

# Set QT_API to pyqt6 explicitly before any other imports to ensure qtpy works correctly in frozen environment
# os.environ['QT_API'] = 'pyqt6'

# Check if running as a bundled app (py2app)
if getattr(sys, 'frozen', False) or 'RESOURCEPATH' in os.environ:
    # Running as bundled app
    try:
        import cwled
        # Add the package directory to sys.path so submodules (main, data, etc.) 
        # can be imported as top-level modules, which the codebase expects
        sys.path.append(os.path.dirname(cwled.__file__))
        import SplashScreen
        SplashScreen.start()        # the logo first: importing the rest takes a few seconds
        from main import main
    except ImportError as e:
        # Fallback or error handling
        print(f"Error: Could not import cwled package in frozen environment: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: An unexpected error occurred in frozen environment: {e}")
        sys.exit(1)
else:
    # Add the src directory to the Python path
    sys.path.append(str(Path(__file__).parent / "cwled"))
    import SplashScreen
    SplashScreen.start()            # the logo first: importing the rest takes a few seconds
    from main import main

if __name__ == "__main__":
    main()
