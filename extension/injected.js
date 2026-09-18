/**
 * Injected vao MAIN world cua trang flow.google.com — co quyen truy cap
 * window.grecaptcha. Port nguyen ven tu du an FlowKit (E:\0 -Flowkit), phan
 * nay khong co gi rieng cua FlowKit ca — chi la cach mint reCAPTCHA dung
 * ngay trong trang that, nen giu y het.
 */
const SITE_KEY = '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV';

window.addEventListener('GET_CAPTCHA', async ({ detail }) => {
  const { requestId, pageAction } = detail;
  try {
    await waitForGrecaptcha();
    const token = await window.grecaptcha.enterprise.execute(SITE_KEY, {
      action: pageAction,
    });
    window.dispatchEvent(new CustomEvent('CAPTCHA_RESULT', {
      detail: { requestId, token },
    }));
  } catch (e) {
    window.dispatchEvent(new CustomEvent('CAPTCHA_RESULT', {
      detail: { requestId, error: e.message },
    }));
  }
});

function waitForGrecaptcha(timeout = 22000) {   // tai lazy; 10s la lac quan qua
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      if (window.grecaptcha?.enterprise?.execute) return resolve();
      if (Date.now() - start > timeout) return reject(new Error('grecaptcha not available'));
      setTimeout(check, 200);
    };
    check();
  });
}
