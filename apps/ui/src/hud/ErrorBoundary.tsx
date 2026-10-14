import { Component, type ErrorInfo, type ReactNode } from 'react';
import { bridge } from '../lib/bridge';

interface Props {
  name: string;
  fallback: ReactNode;
  children: ReactNode;
}

export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    try {
      bridge().reportError({
        kind: error.name,
        message: `[${this.props.name}] ${error.message}`,
        stack: `${error.stack ?? ''}\n${info.componentStack ?? ''}`,
      });
    } catch {
      // nothing else we can do
    }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
