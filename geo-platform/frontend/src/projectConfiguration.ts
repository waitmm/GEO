export function projectConfigurationPayload(values: Record<string, string | undefined>) {
  const { competitors, brand_aliases, ...fields } = values;
  return {
    ...fields,
    brand_aliases: (brand_aliases || '').split(',').map(item => item.trim()).filter(Boolean),
    competitors: (competitors || '').split('\n').filter(line => line.trim()).map(line => {
      const [name, aliases = '', ...url] = line.split(':');
      return { name: name.trim(), aliases: aliases.split(';').map(item => item.trim()).filter(Boolean),
        website_url: url.join(':').trim() };
    }),
  };
}

export function projectConfigurationVersionPath(projectId: number, configurationVersionId: string) {
  return `/api/projects/${projectId}/configuration-versions/${encodeURIComponent(configurationVersionId)}`;
}
