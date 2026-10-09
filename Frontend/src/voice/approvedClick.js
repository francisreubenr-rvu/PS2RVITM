// A proof belongs to one exact app-owned click after the owner's matching pending approval.
// No global dialog interception. Normal human clicks keep their existing confirmation dialogs.
const approvals = new WeakMap();

export function dispatchApprovedClick(element) {
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
  approvals.set(event, { element, route: location.hash });
  element.dispatchEvent(event);
}

export function isAgnezApprovedClick(event) {
  const native = event?.nativeEvent || event;
  if (!native || typeof native !== 'object') return false;
  const proof = approvals.get(native);
  approvals.delete(native);
  return Boolean(proof && proof.element === native.target && proof.element.isConnected && proof.route === location.hash);
}
