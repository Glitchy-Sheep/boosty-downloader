"""
Views: application data in, terminal renderables out.

A view gets a finished data object (BlogOverview, DownloadPlan, RunStatistics)
and returns a rich renderable. It never talks to the API, the cache or the
console: the command that owns the console prints it.
"""
