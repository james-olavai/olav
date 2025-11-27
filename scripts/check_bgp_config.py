#!/usr/bin/env python
"""Check device configurations for BGP settings."""
import pandas as pd
import os
import glob

def check_bgp_config():
    parquet_dir = 'data/suzieq-parquet/coalesced/devconfig'
    files = glob.glob(os.path.join(parquet_dir, '**/*.parquet'), recursive=True)
    print(f'Found {len(files)} devconfig files')

    if not files:
        print("No devconfig parquet files found")
        return

    # Read most recent file
    files.sort(key=os.path.getmtime, reverse=True)
    df = pd.read_parquet(files[0])
    print(f'Columns: {df.columns.tolist()}')
    print(f'\nChecking {len(df)} device configs for BGP:')
    
    for idx, row in df.iterrows():
        hostname = row.get('hostname', 'unknown')
        config = row.get('config', '')
        
        if config:
            has_bgp = 'router bgp' in config.lower() or 'bgp neighbor' in config.lower()
            print(f"\n{hostname}: BGP configured = {has_bgp}")
            
            if has_bgp:
                # Extract BGP section
                lines = config.split('\n')
                in_bgp_section = False
                for line in lines:
                    if 'router bgp' in line.lower():
                        in_bgp_section = True
                    if in_bgp_section:
                        print(f'  {line}')
                        if line.strip() == '!' or line.strip().startswith('router ') and 'bgp' not in line.lower():
                            break

if __name__ == '__main__':
    check_bgp_config()
