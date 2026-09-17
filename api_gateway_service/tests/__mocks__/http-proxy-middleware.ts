let capturedOptions: any = null;

const mockProxyMiddleware = jest.fn((options: any) => {
  capturedOptions = options;
  return (_req: any, _res: any, next: any) => next();
});

function getCapturedOptions(): any {
  return capturedOptions;
}

function resetCapturedOptions(): void {
  capturedOptions = null;
}

module.exports = {
  createProxyMiddleware: mockProxyMiddleware,
  getCapturedOptions,
  resetCapturedOptions,
};
