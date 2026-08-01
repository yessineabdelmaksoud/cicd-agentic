import yaml
import glob
import os

base_path = os.getcwd()
obs_path = os.path.join(base_path, 'observability')

claim_map = {
    'grafana-claim1': f'{obs_path}/grafana/provisioning',
    'grafana-claim2': f'{obs_path}/grafana/dashboards',
    'loki-claim1': f'{obs_path}/loki/loki-config.yaml',
    'prometheus-claim0': f'{obs_path}/prometheus/prometheus.yml',
    'prometheus-claim1': f'{obs_path}/prometheus/rules',
    'promtail-claim0': f'/var/log',
    'promtail-claim1': f'/var/lib/docker/containers',
    'promtail-claim3': f'{obs_path}/promtail/promtail-config.yaml'
}

for f in glob.glob('infra/k3s/**/*-deployment.yaml', recursive=True):
    try:
        with open(f, 'r') as file:
            docs = list(yaml.safe_load_all(file))
        
        modified = False
        for doc in docs:
            if doc and 'spec' in doc and 'template' in doc['spec'] and 'spec' in doc['spec']['template']:
                volumes = doc['spec']['template']['spec'].get('volumes', [])
                for vol in volumes:
                    vol_name = vol.get('name')
                    if vol_name in claim_map and 'hostPath' in vol:
                        expected_path = claim_map[vol_name]
                        expected_type = 'File' if expected_path.endswith('.yml') or expected_path.endswith('.yaml') else 'DirectoryOrCreate'
                        if vol['hostPath']['path'] != expected_path or vol['hostPath'].get('type') != expected_type:
                            vol['hostPath']['path'] = expected_path
                            vol['hostPath']['type'] = expected_type
                            modified = True
        
        if modified:
            with open(f, 'w') as out:
                yaml.dump_all(docs, out)
    except Exception as e:
        print(f"Error processing {f}: {e}")
