import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div className="flex h-screen items-center justify-center p-8">
            <div className="max-w-lg space-y-4 rounded-lg border border-red-300 bg-red-50 p-6 dark:bg-red-950/20">
              <h2 className="text-lg font-semibold text-red-700 dark:text-red-400">
                Component Error
              </h2>
              <pre className="text-sm whitespace-pre-wrap text-red-600 dark:text-red-300 max-h-96 overflow-y-auto">
                {this.state.error.message}
                {"\n\n"}
                {this.state.error.stack?.split("\n").slice(0, 15).join("\n")}
              </pre>
              <button
                type="button"
                className="rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
                onClick={() => this.setState({ error: null })}
              >
                Retry
              </button>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
