import sys

if __name__ == "__main__":
    if "--production-self-test" in sys.argv:
        from app.production_self_test import run_production_self_test

        raise SystemExit(run_production_self_test())

    from comic import main

    main()
