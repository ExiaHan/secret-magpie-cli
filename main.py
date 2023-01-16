from multiprocessing.pool import ThreadPool
from functools import partial
import sys

import csv
import json
import tools
import tasks
import argparsing
import stats
import output
import datetime
import time
import os
import subprocess  # nosec blacklist
import urllib3

ag_grid_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Ag-Grid Basic Example</title>
    <script src="https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js"></script>
    <script>
        const columnDefs = [
                { field: "source" },
                { field: "detector_type" },
                { field: "verified" },
                { field: "commit" },
                { field: "date" },
                { field: "author_email" },
                { field: "repository" },
                { field: "repository_uri" },
                { field: "link" },
                { field: "file" },
                { field: "line" },
                { field: "filename" },
                { field: "extension" },
                { field: "hashed_secret" },
                { field: "secret" },
                { field: "redacted_secret" },
                { field: "context" },
                { field: "extra_context" }
            ];

            // specify the data
            const rowData = $$ROWDATA$$;

            // let the grid know which columns and what data to use
            const gridOptions = {
                columnDefs: columnDefs,
                rowData: rowData
            };

            // setup the grid after the page has finished loading
            document.addEventListener('DOMContentLoaded', () => {
                const gridDiv = document.querySelector('#myGrid');
                new agGrid.Grid(gridDiv, gridOptions);
            });
    </script>
    <link rel="stylesheet">
        href="https://cdn.jsdelivr.net/npm/ag-grid-community/styles/ag-theme-alpine.css"/>
    <style>
        .ag-theme-customtheme{
		--ag-borders: solid 6px;
		--ag-border-color: #1d2024;
		--ag-header-background-color: #1d2024;
            --ag-background-color: black;
		--ag-odd-row-background-color: #1d2024;
		--ag-row-border-color: transparent;
        }
    </style>
</head>
<body style="background-color: #242930; margin: 20px">
    <div id="myGrid" style="height: 1000px; width: 100%;" class="ag-theme-alpine-dark ag-theme-customtheme"></div>
</body>
</html>

"""

if __name__ == "__main__":
    urllib3.disable_warnings()
    print(argparsing.banner)
    args = argparsing.parse_args()
    cleanup = not (args.no_cleanup or "filesystem" == args.provider)

    if args.convert_to_html is None:
        with open(os.devnull, "wb") as devnull:
            if args.update_ca_store:
                subprocess.call(  # nosec subprocess_without_shell_equals_true start_process_with_partial_path
                    ["update-ca-certificates"], stdout=devnull, stderr=devnull
                )

        threshold_date = None
        if args.ignore_branches_older_than != None:
            try:
                threshold_date = time.mktime(
                    datetime.datetime.fromisoformat(
                        args.ignore_branches_older_than
                    ).timetuple()
                )
            except ValueError:
                print("ERROR: Invalid ISO format string.")
                sys.exit(1)

        tool_list = []
        if not args.disable_gitleaks:
            tool_list.append(tools.gitleaks)
        if not args.disable_trufflehog:
            tool_list.append(tools.truffle_hog)
        if len(tool_list) == 0:
            print("ERROR: No tools to scan with")
            sys.exit(1)
        repos = tasks.get_repos(**args.__dict__)
        total_results = []
        f = partial(
            tasks.process_repo,
            functions=tool_list,
            single_branch=args.single_branch,
            extra_context=args.extra_context,
            cleanup=cleanup,
            threshold_date=threshold_date,
            validate_https=not args.dont_validate_https,
            max_branch_count=args.max_branch_count,
        )
        pool = ThreadPool(args.parallel_repos)
        results = pool.imap_unordered(f, repos)
        processed_repos = 0
        with output.Output(args.out_format, args.out) as o:
            for result_batch in results:
                processed_repos += 1
                print(
                    f"          | Processed Repos: {processed_repos} | | Total secret detections: {len(total_results)} |",
                    end="\r",
                    flush=True,
                )
                for result in result_batch:
                    if result.status == "FAIL" or result.findings == []:
                        continue
                    for item in result.findings:
                        total_results.append(item)
                        if args.dont_store_secret:
                            item.secret = ""  # nosec hardcoded_password_string
                            item.context = ""
                            item.extra_context = ""
                        o.write(item)
        print(
            f"          | Processed Repos: {processed_repos} | | Total secret detections: {len(total_results)} |"
        )

        if not args.no_stats:
            s = stats.Stats(total_results, processed_repos)
            print(s.Report())
    else:
        filename = args.convert_to_html
        with open(filename, "r") as f:
            filetype = None
            if filename.endswith(".csv"):
                results = json.dumps(list(csv.DictReader(f)))
            elif filename.endswith(".json"):
                results = f.read()
            else:
                print("ERROR: Invalid input format for HTML conversion.")
                sys.exit(1)

        with open("results.html", "w") as f:
            f.write(ag_grid_template.replace("$$ROWDATA$$", results))
